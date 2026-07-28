from fastapi import APIRouter
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, DbSession
from app.models import (
    Assignment,
    Group,
    GroupMember,
    Lesson,
    ParentLink,
    Report,
    ReportAudience,
    ReportStatus,
    Submission,
    SubmissionStatus,
    User,
    UserRole,
)
from app.schemas.activity import ActivityItem, ActivitySummary
from app.schemas.auth import UserOut
from app.schemas.groups import GroupOut, SubjectOut, UpcomingLesson

router = APIRouter(prefix="/me", tags=["me"])


@router.get("/groups", response_model=list[GroupOut])
async def my_groups(db: DbSession, user: CurrentUser) -> list[GroupOut]:
    groups = (
        await db.scalars(
            select(Group)
            .join(GroupMember, GroupMember.group_id == Group.id)
            .where(GroupMember.student_id == user.id)
            .options(selectinload(Group.subject))
            .order_by(Group.name)
        )
    ).all()
    return [
        GroupOut(id=g.id, name=g.name, subject=SubjectOut.model_validate(g.subject))
        for g in groups
    ]


@router.get("/lessons", response_model=list[UpcomingLesson])
async def my_lessons(db: DbSession, user: CurrentUser) -> list[UpcomingLesson]:
    rows = (
        await db.execute(
            select(Lesson, Group)
            .join(Group, Group.id == Lesson.group_id)
            .join(GroupMember, GroupMember.group_id == Group.id)
            .where(GroupMember.student_id == user.id)
            .options(selectinload(Group.subject))
            .order_by(Lesson.weekday, Lesson.start_time)
        )
    ).all()
    return [
        UpcomingLesson(
            group_id=group.id,
            group_name=group.name,
            subject_name=group.subject.name,
            weekday=lesson.weekday,
            start_time=lesson.start_time,
            duration_min=lesson.duration_min,
            title=lesson.title,
        )
        for lesson, group in rows
    ]


@router.get("/children", response_model=list[UserOut])
async def my_children(db: DbSession, user: CurrentUser) -> list[UserOut]:
    children = (
        await db.scalars(
            select(User)
            .join(ParentLink, ParentLink.student_id == User.id)
            .where(ParentLink.parent_id == user.id)
            .order_by(User.name)
        )
    ).all()
    return [UserOut.model_validate(c) for c in children]


ACTIVITY_LIMIT = 12


@router.get("/activity", response_model=ActivitySummary)
async def my_activity(db: DbSession, user: CurrentUser) -> ActivitySummary:
    """What needs this user's attention, derived from existing rows.

    There is no read/unread state: for a tutor "pending" is a fact about the
    work, not about whether they glanced at a bell, and students and parents
    are shown their most recent results. That keeps this a plain read with no
    extra table to keep in sync.
    """
    if user.role in (UserRole.tutor, UserRole.admin):
        return await _tutor_activity(db, user)
    if user.role == UserRole.student:
        return await _student_activity(db, user)
    return await _parent_activity(db, user)


async def _tutor_activity(db, user: User) -> ActivitySummary:
    rows = (
        await db.execute(
            select(Submission, Assignment, Group, User)
            .join(Assignment, Assignment.id == Submission.assignment_id)
            .join(Group, Group.id == Assignment.group_id)
            .join(User, User.id == Submission.student_id)
            .where(
                Group.tutor_id == user.id,
                Submission.status != SubmissionStatus.finalized,
            )
            .order_by(Submission.submitted_at.desc())
            .limit(ACTIVITY_LIMIT)
        )
    ).all()
    total = await db.scalar(
        select(func.count(Submission.id))
        .join(Assignment, Assignment.id == Submission.assignment_id)
        .join(Group, Group.id == Assignment.group_id)
        .where(Group.tutor_id == user.id, Submission.status != SubmissionStatus.finalized)
    )
    return ActivitySummary(
        count=total or 0,
        items=[
            ActivityItem(
                kind="submission_awaiting_review",
                label=f"{student.name} submitted {assignment.title}",
                sublabel=group.name,
                link=f"/tutor/groups/{group.id}/submissions/{submission.id}",
                occurred_at=submission.submitted_at,
            )
            for submission, assignment, group, student in rows
        ],
    )


async def _student_activity(db, user: User) -> ActivitySummary:
    rows = (
        await db.execute(
            select(Submission, Assignment)
            .join(Assignment, Assignment.id == Submission.assignment_id)
            .where(
                Submission.student_id == user.id,
                Submission.status == SubmissionStatus.finalized,
            )
            .order_by(Submission.finalized_at.desc())
            .limit(ACTIVITY_LIMIT)
        )
    ).all()
    return ActivitySummary(
        count=len(rows),
        items=[
            ActivityItem(
                kind="homework_marked",
                label=f"{assignment.title} has been marked",
                link=f"/student/homework/{assignment.id}",
                occurred_at=submission.finalized_at or submission.submitted_at,
            )
            for submission, assignment in rows
        ],
    )


async def _parent_activity(db, user: User) -> ActivitySummary:
    rows = (
        await db.execute(
            select(Report, User)
            .join(User, User.id == Report.student_id)
            .join(ParentLink, ParentLink.student_id == Report.student_id)
            .where(
                ParentLink.parent_id == user.id,
                Report.audience == ReportAudience.parent,
                Report.status == ReportStatus.ready,
            )
            .order_by(Report.created_at.desc())
            .limit(ACTIVITY_LIMIT)
        )
    ).all()
    return ActivitySummary(
        count=len(rows),
        items=[
            ActivityItem(
                kind="report_ready",
                label=f"New report for {student.name}",
                sublabel=report.title,
                link="/parent",
                occurred_at=report.generated_at or report.created_at,
            )
            for report, student in rows
        ],
    )
