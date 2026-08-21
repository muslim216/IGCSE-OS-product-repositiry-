"""The Student CRM aggregation — the student's continuously-updating academic
record.

Shaped as one aggregation because it was the single source of truth for both
the CRM UI and the AI's grounding context: services/student_context.py read
from it, so the two surfaces could never drift apart. That second reader was
deleted with the student AI chat (AV-57) and the shape is now carried by the
CRM UI alone — but the reason it is one aggregation rather than several
per-screen queries is recorded here, because the next AI surface that needs a
student's record should read this rather than grow its own."""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
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
    SubmissionStatus,
    TutorNote,
    User,
)
from app.schemas.readiness import SubjectReadiness
from app.services.readiness_summary import build_summary


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


async def get_student_crm(session: AsyncSession, student: User) -> StudentCrm:
    profile = await session.scalar(
        select(StudentProfile).where(StudentProfile.student_id == student.id)
    )

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
    readiness_summary = await build_summary(session, student, subject_ids)

    homework_rows = (
        await session.execute(
            select(Assignment, Submission)
            .join(Group, Group.id == Assignment.group_id)
            .join(GroupMember, GroupMember.group_id == Group.id)
            .outerjoin(
                Submission,
                (Submission.assignment_id == Assignment.id) & (Submission.student_id == student.id),
            )
            .where(
                GroupMember.student_id == student.id,
                Assignment.status.in_([AssignmentStatus.published, AssignmentStatus.closed]),
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
        if submission is not None and submission.status == SubmissionStatus.finalized:
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

    notes = (
        await session.scalars(
            select(TutorNote)
            .where(TutorNote.student_id == student.id)
            .order_by(TutorNote.created_at.desc())
        )
    ).all()
    communications = (
        await session.scalars(
            select(ParentCommunication)
            .where(ParentCommunication.student_id == student.id)
            .order_by(ParentCommunication.created_at.desc())
        )
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
