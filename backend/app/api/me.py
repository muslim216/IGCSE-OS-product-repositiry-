from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, DbSession
from app.models import (
    Assignment,
    Group,
    GroupMember,
    ParentLink,
    PastPaper,
    Report,
    ReportAudience,
    ReportStatus,
    ScheduleSlot,
    Submission,
    SubmissionStatus,
    User,
    UserRole,
)
from app.schemas.activity import ActivityItem, ActivitySummary
from app.schemas.auth import UserOut
from app.schemas.groups import GroupOut, SubjectOut, UpcomingScheduleSlot
from app.services.groups import AWAITING_REVIEW

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


@router.get("/lessons", response_model=list[UpcomingScheduleSlot])
async def my_lessons(db: DbSession, user: CurrentUser) -> list[UpcomingScheduleSlot]:
    rows = (
        await db.execute(
            select(ScheduleSlot, Group)
            .join(Group, Group.id == ScheduleSlot.group_id)
            .join(GroupMember, GroupMember.group_id == Group.id)
            .where(GroupMember.student_id == user.id)
            .options(selectinload(Group.subject))
            .order_by(ScheduleSlot.weekday, ScheduleSlot.start_time)
        )
    ).all()
    return [
        UpcomingScheduleSlot(
            id=slot.id,
            group_id=group.id,
            group_name=group.name,
            subject_name=group.subject.name,
            weekday=slot.weekday,
            start_time=slot.start_time,
            duration_min=slot.duration_min,
            title=slot.title,
        )
        for slot, group in rows
    ]


@router.get("/today-lessons", response_model=list[UpcomingScheduleSlot])
async def my_today_lessons(db: DbSession, user: CurrentUser) -> list[UpcomingScheduleSlot]:
    if user.role not in (UserRole.tutor, UserRole.admin):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Tutor account required")
    today_weekday = datetime.now(timezone.utc).weekday()
    rows = (
        await db.execute(
            select(ScheduleSlot, Group, func.count(GroupMember.id))
            .join(Group, Group.id == ScheduleSlot.group_id)
            .outerjoin(GroupMember, GroupMember.group_id == Group.id)
            .where(Group.tutor_id == user.id, ScheduleSlot.weekday == today_weekday)
            .options(selectinload(Group.subject))
            .group_by(ScheduleSlot.id, Group.id)
            .order_by(ScheduleSlot.start_time)
        )
    ).all()
    return [
        UpcomingScheduleSlot(
            id=slot.id,
            group_id=group.id,
            group_name=f"{group.name} ({count} student{'s' if count != 1 else ''})",
            subject_name=group.subject.name,
            weekday=slot.weekday,
            start_time=slot.start_time,
            duration_min=slot.duration_min,
            title=slot.title,
        )
        for slot, group, count in rows
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

    There is no read/unread state: for a tutor "waiting on you" is a fact about
    the work, not about whether they glanced at a bell, and students and parents
    are shown their most recent results. That keeps this a plain read with no
    extra table to keep in sync.
    """
    if user.role in (UserRole.tutor, UserRole.admin):
        return await _tutor_activity(db, user)
    if user.role == UserRole.student:
        return await _student_activity(db, user)
    return await _parent_activity(db, user)


def _tutor_scope(user: User):
    """Submissions belonging to this tutor's organization.

    Left-joined both ways: a submission belongs to an assignment (homework) or
    to a past paper, never both, and both land in the tutor's queue.
    """
    return (
        select(Submission, Assignment, PastPaper, User)
        .outerjoin(Assignment, Assignment.id == Submission.assignment_id)
        .outerjoin(Group, Group.id == Assignment.group_id)
        .outerjoin(PastPaper, PastPaper.id == Submission.past_paper_id)
        .join(User, User.id == Submission.student_id)
        .where(
            Submission.status.in_(AWAITING_REVIEW),
            (Group.organization_id == user.organization_id)
            | (PastPaper.organization_id == user.organization_id),
        )
    )


async def _tutor_activity(db, user: User) -> ActivitySummary:
    rows = (
        await db.execute(
            _tutor_scope(user).order_by(Submission.submitted_at.desc()).limit(ACTIVITY_LIMIT)
        )
    ).all()
    total = len((await db.execute(_tutor_scope(user))).all())
    return ActivitySummary(
        count=total,
        items=[
            ActivityItem(
                kind="submission_awaiting_review",
                label=f"{student.name} submitted "
                + (
                    assignment.title
                    if assignment
                    else f"{past_paper.session_label} {past_paper.paper_number}"
                ),
                sublabel="Past paper" if past_paper else None,
                link=f"/tutor/submissions/{submission.id}",
                occurred_at=submission.submitted_at,
            )
            for submission, assignment, past_paper, student in rows
        ],
    )


async def _student_activity(db, user: User) -> ActivitySummary:
    """A student's own marked work. Auto-finalized counts too — the mark is
    final and visible to them, whether or not a tutor had to touch it."""
    rows = (
        await db.execute(
            select(Submission, Assignment)
            .join(Assignment, Assignment.id == Submission.assignment_id)
            .where(
                Submission.student_id == user.id,
                Submission.status.in_(
                    (SubmissionStatus.finalized, SubmissionStatus.auto_finalized)
                ),
            )
            .order_by(Submission.finalized_at.desc(), Submission.submitted_at.desc())
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
                label=f"New progress report for {student.name}",
                link="/parent",
                occurred_at=report.created_at,
            )
            for report, student in rows
        ],
    )
