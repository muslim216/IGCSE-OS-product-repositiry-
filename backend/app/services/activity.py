"""The activity feed: what needs a user's attention right now.

Derived entirely from existing rows — there is no read/unread state. For a
tutor "waiting on you" is a fact about the work, not about whether they glanced
at a bell, and students and parents are shown their most recent results. That
keeps this a plain read with no extra table to keep in sync.
"""

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    SETTLED_STATUSES,
    Assignment,
    Group,
    Mock,
    ParentLink,
    PastPaper,
    Report,
    ReportAudience,
    ReportStatus,
    Submission,
    User,
    UserRole,
)
from app.schemas.activity import ActivityItem, ActivitySummary
from app.services.groups import AWAITING_REVIEW

#: Most recent items returned; the summary's `count` is the true total.
ACTIVITY_LIMIT = 12


def _work_title(
    assignment: Assignment | None, past_paper: PastPaper | None, mock: Mock | None
) -> str:
    """Submissions are polymorphic — name whichever side is set."""
    if assignment is not None:
        return assignment.title
    if past_paper is not None:
        return past_paper.display_title
    if mock is not None:
        return mock.title
    return "Work"


def _polymorphic_submissions() -> Select:
    """Submissions joined to every kind of work they can belong to.

    Left-joined three ways: a submission belongs to an assignment (homework), a
    past paper or a mock, never more than one, so an inner join on any of them
    would silently drop the other two thirds. Miss an arm here and the feed does
    not raise — it reads a `None` as though the work did not exist (`API-20`).
    """
    return (
        select(Submission, Assignment, PastPaper, Mock)
        .outerjoin(Assignment, Assignment.id == Submission.assignment_id)
        .outerjoin(PastPaper, PastPaper.id == Submission.past_paper_id)
        .outerjoin(Mock, Mock.id == Submission.mock_id)
    )


def tutor_scope(user: User) -> Select:
    """Work awaiting review across this tutor's organization."""
    return (
        _polymorphic_submissions()
        .add_columns(User)
        .outerjoin(Group, Group.id == Assignment.group_id)
        .join(User, User.id == Submission.student_id)
        .where(
            Submission.status.in_(AWAITING_REVIEW),
            (Group.organization_id == user.organization_id)
            | (PastPaper.organization_id == user.organization_id)
            | (Mock.organization_id == user.organization_id),
        )
    )


async def _count(session: AsyncSession, scope: Select) -> int:
    """The true total behind a feed, which `items` is capped below."""
    return (await session.execute(select(func.count()).select_from(scope.subquery()))).scalar_one()


async def for_user(session: AsyncSession, user: User) -> ActivitySummary:
    if user.role in (UserRole.tutor, UserRole.admin):
        return await _tutor_activity(session, user)
    if user.role == UserRole.student:
        return await _student_activity(session, user)
    return await _parent_activity(session, user)


async def _tutor_activity(session: AsyncSession, user: User) -> ActivitySummary:
    scope = tutor_scope(user)
    rows = (
        await session.execute(scope.order_by(Submission.submitted_at.desc()).limit(ACTIVITY_LIMIT))
    ).all()
    return ActivitySummary(
        count=await _count(session, scope),
        items=[
            ActivityItem(
                kind="submission_awaiting_review",
                label=f"{student.name} submitted {_work_title(assignment, past_paper, mock)}",
                sublabel=(
                    "Past paper" if past_paper is not None else "Mock" if mock is not None else None
                ),
                link=f"/tutor/submissions/{submission.id}",
                occurred_at=submission.submitted_at,
            )
            for submission, assignment, past_paper, mock, student in rows
        ],
    )


async def _student_activity(session: AsyncSession, user: User) -> ActivitySummary:
    """A student's own marked work — homework and past papers alike."""
    scope = _polymorphic_submissions().where(
        Submission.student_id == user.id, Submission.status.in_(SETTLED_STATUSES)
    )
    rows = (
        await session.execute(
            scope.order_by(Submission.finalized_at.desc(), Submission.submitted_at.desc()).limit(
                ACTIVITY_LIMIT
            )
        )
    ).all()
    return ActivitySummary(
        count=await _count(session, scope),
        items=[
            ActivityItem(
                kind="homework_marked",
                label=f"{_work_title(assignment, past_paper, mock)} has been marked",
                link=(
                    f"/student/homework/{assignment.id}"
                    if assignment is not None
                    else f"/student/past-papers/{past_paper.id}"
                    if past_paper is not None
                    else f"/student/mocks/{mock.id}"
                ),
                occurred_at=submission.finalized_at or submission.submitted_at,
            )
            for submission, assignment, past_paper, mock in rows
        ],
    )


async def _parent_activity(session: AsyncSession, user: User) -> ActivitySummary:
    scope = (
        select(Report, User)
        .join(User, User.id == Report.student_id)
        .join(ParentLink, ParentLink.student_id == Report.student_id)
        .where(
            ParentLink.parent_id == user.id,
            Report.audience == ReportAudience.parent,
            Report.status == ReportStatus.ready,
        )
    )
    rows = (
        await session.execute(scope.order_by(Report.created_at.desc()).limit(ACTIVITY_LIMIT))
    ).all()
    return ActivitySummary(
        count=await _count(session, scope),
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
