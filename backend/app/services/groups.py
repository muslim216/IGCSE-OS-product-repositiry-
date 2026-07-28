"""Group (class) aggregation: the counts and next-lesson pick behind the
tutor's class cards."""

from collections import defaultdict
from datetime import datetime, time

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Assignment,
    AssignmentStatus,
    GroupMember,
    ScheduleSlot,
    Submission,
    SubmissionStatus,
)
from app.models.base import utcnow
from app.schemas.groups import GroupSummary, NextLesson

#: Submission states that are waiting on the tutor's eyes, mirroring the
#: attention endpoint: an AI draft to confirm, an AI failure to handle, or
#: auto-marking's uncertain rows. Finalized and auto-finalized work is done;
#: submitted/marking is still in flight.
AWAITING_REVIEW = (
    SubmissionStatus.ai_marked,
    SubmissionStatus.ai_failed,
    SubmissionStatus.needs_review,
)


def soonest_slot(slots: list[ScheduleSlot], now: datetime) -> NextLesson | None:
    """Pick the next occurrence of a weekly timetable.

    Pure, so it unit-tests without a database. Slots repeat weekly (weekday +
    start_time, no date), so "next" means the smallest number of days ahead; a
    slot earlier today has already passed and rolls round to next week.
    """
    if not slots:
        return None
    today, current = now.weekday(), now.time()

    def days_away(slot: ScheduleSlot) -> tuple[int, time]:
        days = (slot.weekday - today) % 7
        if days == 0 and slot.start_time <= current:
            days = 7
        return days, slot.start_time

    nxt = min(slots, key=days_away)
    return NextLesson(
        weekday=nxt.weekday,
        start_time=nxt.start_time,
        duration_min=nxt.duration_min,
        title=nxt.title,
    )


async def summaries(session: AsyncSession, group_ids: list[int]) -> dict[int, GroupSummary]:
    """Per-group counts for the class cards.

    Each aggregate is its own query rather than one wide join: joining members,
    assignments and submissions together would multiply the rows and inflate
    every count.
    """
    if not group_ids:
        return {}

    members = dict(
        (
            await session.execute(
                select(GroupMember.group_id, func.count(GroupMember.id))
                .where(GroupMember.group_id.in_(group_ids))
                .group_by(GroupMember.group_id)
            )
        ).all()
    )
    published = dict(
        (
            await session.execute(
                select(Assignment.group_id, func.count(Assignment.id))
                .where(
                    Assignment.group_id.in_(group_ids),
                    Assignment.status == AssignmentStatus.published,
                )
                .group_by(Assignment.group_id)
            )
        ).all()
    )
    awaiting = dict(
        (
            await session.execute(
                select(Assignment.group_id, func.count(Submission.id))
                .join(Assignment, Assignment.id == Submission.assignment_id)
                .where(
                    Assignment.group_id.in_(group_ids),
                    Submission.status.in_(AWAITING_REVIEW),
                )
                .group_by(Assignment.group_id)
            )
        ).all()
    )

    by_group: dict[int, list[ScheduleSlot]] = defaultdict(list)
    for slot in (
        await session.scalars(select(ScheduleSlot).where(ScheduleSlot.group_id.in_(group_ids)))
    ).all():
        by_group[slot.group_id].append(slot)

    now = utcnow()
    return {
        gid: GroupSummary(
            member_count=members.get(gid, 0),
            published_assignment_count=published.get(gid, 0),
            awaiting_review_count=awaiting.get(gid, 0),
            next_lesson=soonest_slot(by_group.get(gid, []), now),
        )
        for gid in group_ids
    }
