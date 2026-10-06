"""The Student CRM aggregation — the student's continuously-updating academic
record. This is the single source of truth for both the CRM UI and the AI's
grounding context (services/student_context.py reads from it too), so the two
surfaces can never drift apart."""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    SETTLED_STATUSES,
    Assignment,
    AssignmentQuestion,
    AssignmentStatus,
    Group,
    GroupMember,
    ParentCommunication,
    QuestionMark,
    StudentProfile,
    StudentSubject,
    Subject,
    Submission,
    TutorNote,
    User,
    UserRole,
)
from app.schemas.readiness import SubjectReadiness
from app.services.readiness_summary_v2 import build_summary_v2


@dataclass(frozen=True)
class Enrollment:
    subject_id: int
    subject_name: str
    exam_board: str
    target_grade: str | None


@dataclass(frozen=True)
class HomeworkItem:
    assignment_id: int
    title: str
    status: str
    due_at: datetime | None
    submission_status: str | None
    total_final: int | None
    total_max: int


@dataclass(frozen=True)
class StudentCrm:
    student: User
    profile: StudentProfile | None
    enrollments: list[Enrollment]
    readiness: list[SubjectReadiness]
    homework: list[HomeworkItem]
    notes: list[TutorNote]
    communications: list[ParentCommunication]


async def enrolled_subject_ids(session: AsyncSession, student_id: int) -> list[int]:
    """Subjects the student is enrolled in via group membership — used to
    scope the readiness summary regardless of the CRM's own enrollment rows."""
    rows = (
        await session.scalars(
            select(Group.subject_id)
            .join(GroupMember, GroupMember.group_id == Group.id)
            .where(GroupMember.student_id == student_id)
            .distinct()
        )
    ).all()
    return list(rows)


async def get_student_crm(session: AsyncSession, student: User, viewer: User) -> StudentCrm:
    # A student can sit in a second organization's class, so a tutor or admin
    # there can open this record. What one organization wrote about a family —
    # the profile with the parent's contact details, tutor notes, parent
    # communications — is that organization's, and is not handed to the other
    # (`SEC-7`). The student and their parent read their own record unscoped.
    staff_org = viewer.organization_id if viewer.role in (UserRole.tutor, UserRole.admin) else None
    profile_query = select(StudentProfile).where(StudentProfile.student_id == student.id)
    if staff_org is not None:
        profile_query = profile_query.where(StudentProfile.organization_id == staff_org)
    profile = await session.scalar(profile_query)

    enrollment_rows = (
        await session.scalars(select(StudentSubject).where(StudentSubject.student_id == student.id))
    ).all()
    enrollments: list[Enrollment] = []
    for row in enrollment_rows:
        subject = await session.get(Subject, row.subject_id)
        if subject is None:
            continue
        enrollments.append(
            Enrollment(
                subject_id=subject.id,
                subject_name=subject.name,
                exam_board=subject.exam_board,
                target_grade=row.target_grade,
            )
        )

    subject_ids = await enrolled_subject_ids(session, student.id)
    readiness_summary = await build_summary_v2(session, student, subject_ids)

    homework_rows = (
        await session.execute(
            select(Assignment, Submission)
            .join(Group, Group.id == Assignment.group_id)
            .join(GroupMember, GroupMember.group_id == Group.id)
            .outerjoin(
                Submission,
                (Submission.work_id == Assignment.work_id) & (Submission.student_id == student.id),
            )
            .where(
                GroupMember.student_id == student.id,
                Assignment.status.in_([AssignmentStatus.published, AssignmentStatus.closed]),
                # Same rule as readiness: a deleted class's not-yet-due homework
                # was never missed, the student just can no longer hand it in.
                or_(
                    Group.deleted_at.is_(None),
                    Submission.id.is_not(None),
                    Assignment.due_at <= Group.deleted_at,
                ),
            )
            .order_by(Assignment.due_at.desc())
            .limit(20)
        )
    ).all()
    homework: list[HomeworkItem] = []
    for assignment, submission in homework_rows:
        total_max = (
            await session.scalar(
                select(func.coalesce(func.sum(AssignmentQuestion.max_marks), 0)).where(
                    AssignmentQuestion.assignment_id == assignment.id
                )
            )
            or 0
        )
        total_final = None
        if submission is not None and submission.status in SETTLED_STATUSES:
            total_final = await session.scalar(
                select(func.coalesce(func.sum(QuestionMark.final_marks), 0)).where(
                    QuestionMark.submission_id == submission.id
                )
            )
        homework.append(
            HomeworkItem(
                assignment_id=assignment.id,
                title=assignment.title,
                status=assignment.status.value,
                due_at=assignment.due_at,
                submission_status=submission.status.value if submission else None,
                total_final=total_final,
                total_max=total_max,
            )
        )

    notes_query = select(TutorNote).where(TutorNote.student_id == student.id)
    comms_query = select(ParentCommunication).where(ParentCommunication.student_id == student.id)
    if staff_org is not None:
        # Neither row carries an organization; the author's is the tenant.
        authors = select(User.id).where(User.organization_id == staff_org)
        notes_query = notes_query.where(TutorNote.tutor_id.in_(authors))
        comms_query = comms_query.where(ParentCommunication.tutor_id.in_(authors))
    notes = (await session.scalars(notes_query.order_by(TutorNote.created_at.desc()))).all()
    communications = (
        await session.scalars(comms_query.order_by(ParentCommunication.created_at.desc()))
    ).all()

    return StudentCrm(
        student=student,
        profile=profile,
        enrollments=enrollments,
        readiness=readiness_summary.subjects,
        homework=homework,
        notes=list(notes),
        communications=list(communications),
    )
