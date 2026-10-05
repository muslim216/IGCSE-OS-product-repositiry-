import logging

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, DbSession, TutorUser, assert_tutor, owned_subject
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
from app.schemas.attendance import StudentAttendanceOut
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
from app.schemas.custom_criteria import CustomCriterionScoreIn, StudentCriterionScoreOut
from app.schemas.groups import InviteOut
from app.schemas.mistake_rollup import StudentMistakeRollup
from app.schemas.tutor_lists import TutorStudentRow
from app.services.attendance import student_attendance
from app.services.custom_criteria import (
    CriterionConflict,
    CriterionNotFound,
    clear_score,
    criteria_for_student,
    set_score,
    subject_names,
)
from app.services.invites import build_invite
from app.services.mistake_rollup import roll_up_mistakes
from app.services.student_crm import get_student_crm
from app.services.tutor_lists import tutor_students

router = APIRouter(prefix="/students", tags=["students"])
log = logging.getLogger("api")


async def _in_organization(db: AsyncSession, student: User, organization_id: int) -> bool:
    """Homed in this organization, or a member of one of its classes — the rule
    `api/readiness.visible_subject_ids` applies to an admin. A student can sit
    in a second organization's class, so home organization alone gave an admin
    less reach than a tutor beside them: the tutor opened the student, the
    admin got a 404."""
    if student.organization_id == organization_id:
        return True
    membership = await db.scalar(
        select(GroupMember.id)
        .join(Group, Group.id == GroupMember.group_id)
        .where(GroupMember.student_id == student.id, Group.organization_id == organization_id)
        .limit(1)
    )
    return membership is not None


async def _viewable_student(db: AsyncSession, viewer: User, student_id: int) -> User:
    """Students see their own record; parents see linked children's; tutors
    see only students they share a group with; admins see everyone homed in
    their own organization or sitting in one of its classes.

    Every refusal is a 404, never a 403: student ids are enumerable, and a 403
    confirms that one exists (`API-7`, `SEC-9`)."""
    not_found = HTTPException(status.HTTP_404_NOT_FOUND, "Student not found")
    student = await db.get(User, student_id)
    if student is None or student.role != UserRole.student:
        raise not_found
    if viewer.role == UserRole.admin:
        # An admin has wider reach inside their organization, not across
        # organizations (`SEC-7`). Without this the role alone was the whole
        # check, and an admin in one tenant read another's students.
        if not await _in_organization(db, student, viewer.organization_id):
            raise not_found
        return student
    if viewer.role == UserRole.student:
        if viewer.id != student_id:
            raise not_found
        return student
    if viewer.role == UserRole.parent:
        link = await db.scalar(
            select(ParentLink).where(
                ParentLink.parent_id == viewer.id, ParentLink.student_id == student_id
            )
        )
        if link is None:
            raise not_found
        return student
    if viewer.role == UserRole.tutor:
        shares_group = await db.scalar(
            select(GroupMember.id)
            .join(Group, Group.id == GroupMember.group_id)
            .where(GroupMember.student_id == student_id, Group.tutor_id == viewer.id)
        )
        if shares_group is None:
            raise not_found
        return student
    raise not_found


async def _tutor_student(db: AsyncSession, tutor: User, student_id: int) -> User:
    """CRM record edits (profile, enrollments, notes, communications) are
    tutor-only, and only for a student the tutor actually teaches."""
    assert_tutor(tutor)
    student = await db.get(User, student_id)
    if student is None or student.role != UserRole.student:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Student not found")
    if tutor.role == UserRole.admin:
        # Inside the admin's own organization only (`SEC-7`) — this helper
        # guards parent-code, which hands over a named child's whole record.
        if not await _in_organization(db, student, tutor.organization_id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Student not found")
        return student
    shares_group = await db.scalar(
        select(GroupMember.id)
        .join(Group, Group.id == GroupMember.group_id)
        .where(GroupMember.student_id == student_id, Group.tutor_id == tutor.id)
    )
    if shares_group is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Student not found")
    return student


@router.get("", response_model=list[TutorStudentRow])
async def list_my_students(db: DbSession, user: TutorUser) -> list[TutorStudentRow]:
    """Every student in the caller's classes, once each, by name, capped at 500
    (`STUDENT_LIST_LIMIT`). Nothing derived: who they are and which classes."""
    return await tutor_students(db, user)


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
    crm = await get_student_crm(db, student, user)
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
    elif profile.organization_id != user.organization_id:
        # One profile row per student, and it belongs to the organization that
        # wrote it. A tutor who teaches the student in a second organization
        # cannot read it (services/student_crm.py) and must not overwrite it —
        # that would replace another tenant's parent contact details (`SEC-7`).
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This student's profile is kept by another organization and can't be edited here.",
        )
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
    subject = await owned_subject(db, body.subject_id, user)
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


@router.get("/{student_id}/attendance", response_model=StudentAttendanceOut)
async def student_attendance_view(
    student_id: int, db: DbSession, user: CurrentUser
) -> StudentAttendanceOut:
    """A student's attendance for a tutor who teaches them, an admin of their
    organization, or a linked parent. `_viewable_student` is the one ownership
    check (a refusal is a 404, `API-7`). The organization is the viewing staff
    member's own, so a tutor never reads another tenant's lessons (`SEC-7`); a
    parent reads in the child's home organization.
    """
    student = await _viewable_student(db, user, student_id)
    staff = user.role in (UserRole.tutor, UserRole.admin)
    result = await student_attendance(
        db,
        student_id=student.id,
        organization_id=user.organization_id if staff else student.organization_id,
        # A tutor sees only the classes they teach; admin, parent and student see all.
        tutor_id=user.id if user.role == UserRole.tutor else None,
    )
    return StudentAttendanceOut.model_validate(result)


@router.get("/{student_id}/mistakes", response_model=StudentMistakeRollup)
async def student_mistakes(
    student_id: int, subject_id: int, db: DbSession, user: TutorUser
) -> StudentMistakeRollup:
    """Where this student's tagged mistakes fall across one subject's syllabus.

    `subject_id` is a query parameter, not a second path segment: a rollup is a
    read of one student filtered to one subject, and the student is the thing
    being addressed. Both ids are authorized before the service sees either —
    `_tutor_student` for the student, `owned_subject` for the subject (`SEC-8`:
    subjects are global, so subject-only scoping leaks across tenants). Both
    answer **404** rather than 403, because integer keys are enumerable and a
    403 would confirm a row in another tenant exists (`API-7`, `SEC-9`).

    Tutor-facing. The softer student-facing view is a separate surface (4.5)
    with its own gate — severity is an internal weighting signal and reads as a
    verdict to the person who made the mistakes.
    """
    student = await _tutor_student(db, user, student_id)
    subject = await owned_subject(db, subject_id, user)
    return await roll_up_mistakes(db, student_id=student.id, subject_id=subject.id)


# ---- Custom criteria scores (task 5.4b) ----
#
# Hand-entered by a tutor, shown beside readiness and never in it. Writes need
# a tutor who teaches the student (`_tutor_student`) and owns the criterion;
# either failing is a 404 (`API-7`). Reading is wider (owner decision 18): the
# student sees their own scores and a linked parent their child's, each
# labelled "tutor-entered" by the client from `source` (`PROD-8`).


def _criterion_error(exc: Exception) -> HTTPException:
    if isinstance(exc, CriterionNotFound):
        return HTTPException(status.HTTP_404_NOT_FOUND, "Criterion not found")
    return HTTPException(status.HTTP_409_CONFLICT, str(exc))


@router.get("/{student_id}/custom-criteria", response_model=list[StudentCriterionScoreOut])
async def student_custom_criteria(
    student_id: int, db: DbSession, user: CurrentUser
) -> list[StudentCriterionScoreOut]:
    student = await _viewable_student(db, user, student_id)
    # A tutor or admin reads their own organization's criteria. It is not
    # always the student's: a student can sit in a second organization's class,
    # and that tutor passing the student's home organization here was shown the
    # home organization's criteria and the scores on them (`SEC-7`). A student
    # or parent has no organization of their own to read by, so they keep the
    # student's.
    organization_id = (
        user.organization_id
        if user.role in (UserRole.tutor, UserRole.admin)
        else student.organization_id
    )
    rows = await criteria_for_student(db, organization_id, student.id)
    names = await subject_names(db, [criterion for criterion, _ in rows], organization_id)
    return [
        StudentCriterionScoreOut(
            criterion_id=criterion.id,
            name=criterion.name,
            description=criterion.description,
            subject_id=criterion.subject_id,
            subject_name=names.get(criterion.subject_id) if criterion.subject_id else None,
            score=None if score is None else score.score,
            updated_at=None if score is None else score.updated_at,
            updated_by_id=None if score is None else score.updated_by_id,
        )
        for criterion, score in rows
    ]


@router.put("/{student_id}/custom-criteria/{criterion_id}", response_model=StudentCriterionScoreOut)
async def score_custom_criterion(
    student_id: int,
    criterion_id: int,
    body: CustomCriterionScoreIn,
    db: DbSession,
    user: TutorUser,
) -> StudentCriterionScoreOut:
    student = await _tutor_student(db, user, student_id)
    try:
        criterion, score = await set_score(
            db, user.organization_id, student.id, criterion_id, body.score, user.id
        )
        await db.commit()
    except (CriterionNotFound, CriterionConflict) as exc:
        raise _criterion_error(exc) from exc
    except IntegrityError as exc:
        # Two tutors giving this student their first score on this criterion
        # at the same moment; the unique constraint kept one. Say so rather
        # than 500 — the tutor re-reads and decides whether to overwrite.
        # Logged, because the same catch would also hide a CHECK or FK
        # violation behind this benign message.
        log.warning(
            "custom criterion score conflict student=%s criterion=%s",
            student.id,
            criterion_id,
            exc_info=exc,
        )
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Someone else scored this at the same moment. Reload to see their score.",
        ) from exc
    return StudentCriterionScoreOut(
        criterion_id=criterion.id,
        name=criterion.name,
        description=criterion.description,
        subject_id=criterion.subject_id,
        subject_name=(await subject_names(db, [criterion], user.organization_id)).get(
            criterion.subject_id
        )
        if criterion.subject_id
        else None,
        score=score.score,
        updated_at=score.updated_at,
        updated_by_id=score.updated_by_id,
    )


@router.delete(
    "/{student_id}/custom-criteria/{criterion_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def clear_custom_criterion(
    student_id: int, criterion_id: int, db: DbSession, user: TutorUser
) -> None:
    student = await _tutor_student(db, user, student_id)
    try:
        await clear_score(db, user.organization_id, student.id, criterion_id, user.id)
    except (CriterionNotFound, CriterionConflict) as exc:
        raise _criterion_error(exc) from exc
    await db.commit()
