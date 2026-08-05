from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, DbSession, assert_tutor
from app.models import (
    Group,
    GroupMember,
    InviteKind,
    ParentCommunication,
    ParentLink,
    StudentProfile,
    StudentSubject,
    Subject,
    TutorNote,
    User,
    UserRole,
)
from app.schemas.crm import (
    CrmHomeworkItem,
    ParentCommunicationCreate,
    ParentCommunicationOut,
    StudentCrmOut,
    StudentProfileOut,
    StudentProfileUpdate,
    StudentSubjectCreate,
    StudentSubjectOut,
    StudentSubjectUpdate,
    TutorNoteCreate,
    TutorNoteOut,
)
from app.schemas.groups import InviteOut
from app.services.invites import build_invite
from app.services.student_crm import get_student_crm

router = APIRouter(prefix="/students", tags=["students"])


async def _viewable_student(db: AsyncSession, viewer: User, student_id: int) -> User:
    """Students see their own record; parents see linked children's; tutors
    see only students they share a group with; admins see everyone."""
    student = await db.get(User, student_id)
    if student is None or student.role != UserRole.student:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Student not found")
    if viewer.role == UserRole.admin:
        return student
    if viewer.role == UserRole.student:
        if viewer.id != student_id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed")
        return student
    if viewer.role == UserRole.parent:
        link = await db.scalar(
            select(ParentLink).where(
                ParentLink.parent_id == viewer.id, ParentLink.student_id == student_id
            )
        )
        if link is None:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed")
        return student
    if viewer.role == UserRole.tutor:
        shares_group = await db.scalar(
            select(GroupMember.id)
            .join(Group, Group.id == GroupMember.group_id)
            .where(GroupMember.student_id == student_id, Group.tutor_id == viewer.id)
        )
        if shares_group is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Student not found")
        return student
    raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed")


async def _tutor_student(db: AsyncSession, tutor: User, student_id: int) -> User:
    """CRM record edits (profile, enrollments, notes, communications) are
    tutor-only, and only for a student the tutor actually teaches."""
    assert_tutor(tutor)
    student = await db.get(User, student_id)
    if student is None or student.role != UserRole.student:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Student not found")
    if tutor.role == UserRole.admin:
        return student
    shares_group = await db.scalar(
        select(GroupMember.id)
        .join(Group, Group.id == GroupMember.group_id)
        .where(GroupMember.student_id == student_id, Group.tutor_id == tutor.id)
    )
    if shares_group is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Student not found")
    return student


@router.post(
    "/{student_id}/parent-code", response_model=InviteOut, status_code=status.HTTP_201_CREATED
)
async def create_parent_code(student_id: int, db: DbSession, user: CurrentUser) -> InviteOut:
    """Generate a code a parent uses to create an account linked to this student."""
    await _tutor_student(db, user, student_id)
    # Single-use: this code hands over one child's whole academic record, and
    # it is meant for one parent. See services/invites.py.
    invite = build_invite(InviteKind.parent_link, created_by_id=user.id, student_id=student_id)
    db.add(invite)
    await db.commit()
    return InviteOut(code=invite.code, kind=invite.kind.value, expires_at=invite.expires_at)


@router.get("/{student_id}/crm", response_model=StudentCrmOut)
async def student_crm(student_id: int, db: DbSession, user: CurrentUser) -> StudentCrmOut:
    """The student's full academic record: profile, enrollments, readiness,
    homework history, tutor notes, and parent communications — one call."""
    student = await _viewable_student(db, user, student_id)
    crm = await get_student_crm(db, student)
    tutor_ids = {n.tutor_id for n in crm.notes} | {c.tutor_id for c in crm.communications}
    tutor_names = {
        t.id: t.name
        for t in (await db.scalars(select(User).where(User.id.in_(tutor_ids or [0])))).all()
    }
    return StudentCrmOut(
        student_id=student.id,
        student_name=student.name,
        profile=(
            StudentProfileOut(
                school=crm.profile.school,
                year_group=crm.profile.year_group,
                parent_name=crm.profile.parent_name,
                parent_email=crm.profile.parent_email,
                parent_phone=crm.profile.parent_phone,
                updated_at=crm.profile.updated_at,
            )
            if crm.profile is not None
            else None
        ),
        enrollments=[
            StudentSubjectOut(
                subject_id=e.subject_id,
                subject_name=e.subject_name,
                exam_board=e.exam_board,
                target_grade=e.target_grade,
            )
            for e in crm.enrollments
        ],
        readiness=crm.readiness,
        homework=[
            CrmHomeworkItem(
                assignment_id=h.assignment_id,
                title=h.title,
                status=h.status,
                due_at=h.due_at,
                submission_status=h.submission_status,
                total_final=h.total_final,
                total_max=h.total_max,
            )
            for h in crm.homework
        ],
        notes=[
            TutorNoteOut(
                id=n.id,
                tutor_id=n.tutor_id,
                tutor_name=tutor_names.get(n.tutor_id, "Unknown"),
                body=n.body,
                created_at=n.created_at,
            )
            for n in crm.notes
        ],
        communications=[
            ParentCommunicationOut(
                id=c.id,
                tutor_id=c.tutor_id,
                tutor_name=tutor_names.get(c.tutor_id, "Unknown"),
                body=c.body,
                created_at=c.created_at,
            )
            for c in crm.communications
        ],
    )


@router.put("/{student_id}/profile", response_model=StudentProfileOut)
async def update_student_profile(
    student_id: int, body: StudentProfileUpdate, db: DbSession, user: CurrentUser
) -> StudentProfileOut:
    student = await _tutor_student(db, user, student_id)
    profile = await db.scalar(select(StudentProfile).where(StudentProfile.student_id == student.id))
    if profile is None:
        profile = StudentProfile(student_id=student.id, organization_id=user.organization_id)
        db.add(profile)
    profile.school = body.school
    profile.year_group = body.year_group
    profile.parent_name = body.parent_name
    profile.parent_email = body.parent_email
    profile.parent_phone = body.parent_phone
    await db.commit()
    await db.refresh(profile)
    return StudentProfileOut(
        school=profile.school,
        year_group=profile.year_group,
        parent_name=profile.parent_name,
        parent_email=profile.parent_email,
        parent_phone=profile.parent_phone,
        updated_at=profile.updated_at,
    )


@router.post(
    "/{student_id}/subjects", response_model=StudentSubjectOut, status_code=status.HTTP_201_CREATED
)
async def enroll_subject(
    student_id: int, body: StudentSubjectCreate, db: DbSession, user: CurrentUser
) -> StudentSubjectOut:
    student = await _tutor_student(db, user, student_id)
    subject = await db.get(Subject, body.subject_id)
    if subject is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Subject not found")
    existing = await db.scalar(
        select(StudentSubject).where(
            StudentSubject.student_id == student.id, StudentSubject.subject_id == subject.id
        )
    )
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Student is already enrolled in this subject")
    enrollment = StudentSubject(
        student_id=student.id, subject_id=subject.id, target_grade=body.target_grade
    )
    db.add(enrollment)
    await db.commit()
    return StudentSubjectOut(
        subject_id=subject.id,
        subject_name=subject.name,
        exam_board=subject.exam_board,
        target_grade=enrollment.target_grade,
    )


@router.patch("/{student_id}/subjects/{subject_id}", response_model=StudentSubjectOut)
async def update_enrollment(
    student_id: int, subject_id: int, body: StudentSubjectUpdate, db: DbSession, user: CurrentUser
) -> StudentSubjectOut:
    student = await _tutor_student(db, user, student_id)
    enrollment = await db.scalar(
        select(StudentSubject).where(
            StudentSubject.student_id == student.id, StudentSubject.subject_id == subject_id
        )
    )
    if enrollment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Enrollment not found")
    enrollment.target_grade = body.target_grade
    subject = await db.get(Subject, subject_id)
    await db.commit()
    return StudentSubjectOut(
        subject_id=subject_id,
        subject_name=subject.name,
        exam_board=subject.exam_board,
        target_grade=enrollment.target_grade,
    )


@router.delete("/{student_id}/subjects/{subject_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_enrollment(
    student_id: int, subject_id: int, db: DbSession, user: CurrentUser
) -> None:
    student = await _tutor_student(db, user, student_id)
    enrollment = await db.scalar(
        select(StudentSubject).where(
            StudentSubject.student_id == student.id, StudentSubject.subject_id == subject_id
        )
    )
    if enrollment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Enrollment not found")
    await db.delete(enrollment)
    await db.commit()


@router.post(
    "/{student_id}/notes", response_model=TutorNoteOut, status_code=status.HTTP_201_CREATED
)
async def add_note(
    student_id: int, body: TutorNoteCreate, db: DbSession, user: CurrentUser
) -> TutorNoteOut:
    student = await _tutor_student(db, user, student_id)
    note = TutorNote(student_id=student.id, tutor_id=user.id, body=body.body)
    db.add(note)
    await db.commit()
    await db.refresh(note)
    return TutorNoteOut(
        id=note.id,
        tutor_id=user.id,
        tutor_name=user.name,
        body=note.body,
        created_at=note.created_at,
    )


@router.post(
    "/{student_id}/communications",
    response_model=ParentCommunicationOut,
    status_code=status.HTTP_201_CREATED,
)
async def add_communication(
    student_id: int, body: ParentCommunicationCreate, db: DbSession, user: CurrentUser
) -> ParentCommunicationOut:
    student = await _tutor_student(db, user, student_id)
    comm = ParentCommunication(student_id=student.id, tutor_id=user.id, body=body.body)
    db.add(comm)
    await db.commit()
    await db.refresh(comm)
    return ParentCommunicationOut(
        id=comm.id,
        tutor_id=user.id,
        tutor_name=user.name,
        body=comm.body,
        created_at=comm.created_at,
    )
