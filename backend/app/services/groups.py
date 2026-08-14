"""Group (class) aggregation: the counts and next-lesson pick behind the
tutor's class cards."""

from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime, time

from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Assignment,
    AssignmentStatus,
    Group,
    GroupMember,
    PastPaper,
    ScheduleSlot,
    Submission,
    SubmissionStatus,
    Topic,
    TopicReadiness,
)
from app.models.base import utcnow
from app.schemas.groups import GroupSummary, NextLesson
from app.services.readiness_summary import CONFIDENT

#: Submission states that are waiting on the tutor's eyes, mirroring the
#: attention endpoint: an AI draft to confirm, an AI failure to handle, or
#: auto-marking's uncertain rows. Finalized and auto-finalized work is done;
#: submitted/marking is still in flight.
AWAITING_REVIEW = (
    SubmissionStatus.ai_marked,
    SubmissionStatus.ai_failed,
    SubmissionStatus.needs_review,
)


def review_queue_predicate(organization_id: int):
    """The one definition of "waiting on a tutor **in the review queue**".

    Distinct from AWAITING_REVIEW above, and deliberately so: that tuple is the
    per-class workload on a class card, which counts an AI draft still to be
    confirmed. The review queue is narrower — only `needs_review` — and is
    scoped by organization rather than by who owns the class, because past
    papers have no group and a tutor covering for a colleague still has to mark
    the work.

    Shared because the home's headline count links straight to the page this
    predicate selects. When the two drifted, the home said "3 pieces to mark"
    and the queue it linked to listed a different set — the count was built
    from AWAITING_REVIEW scoped by `Group.tutor_id`, so it counted AI drafts the
    queue never shows and dropped a colleague's homework the queue does show.
    Both call sites already outer-join Assignment -> Group and PastPaper, so
    this WHERE clause is the whole of the difference.
    """
    return (
        Submission.status == SubmissionStatus.needs_review,
        (Group.organization_id == organization_id) | (PastPaper.organization_id == organization_id),
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

    # Coverage numerator: how many enrolled students the class's readiness
    # picture actually speaks for. A status derived from 2 of 11 students is a
    # statement about a class made from part of it, and must not look like one
    # made from all of it (PROD-2) — so the count travels with member_count.
    # DISTINCT because a student holds one readiness row per topic and would
    # otherwise be counted once per topic they have evidence for.
    # SEC-7: group_ids arrive already scoped to the authenticated tutor by the
    # callers in api/groups.py, so this inherits that scoping rather than
    # re-deriving it from a parameter.
    covered = dict(
        (
            await session.execute(
                select(GroupMember.group_id, func.count(distinct(GroupMember.student_id)))
                .join(Group, Group.id == GroupMember.group_id)
                .join(Topic, Topic.subject_id == Group.subject_id)
                .join(
                    TopicReadiness,
                    (TopicReadiness.topic_id == Topic.id)
                    & (TopicReadiness.student_id == GroupMember.student_id),
                )
                .where(
                    GroupMember.group_id.in_(group_ids),
                    TopicReadiness.confidence.in_(CONFIDENT),
                )
                .group_by(GroupMember.group_id)
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
            students_with_evidence=covered.get(gid, 0),
            published_assignment_count=published.get(gid, 0),
            awaiting_review_count=awaiting.get(gid, 0),
            next_lesson=soonest_slot(by_group.get(gid, []), now),
        )
        for gid in group_ids
    }


async def class_health(
    session: AsyncSession, groups: Sequence[Group]
) -> dict[int, tuple[float | None, int]]:
    """Per-class readiness: the mean of each class's confident learner scores,
    and how many learners contributed.

    One query for every class the tutor has, not one per class and certainly not
    one per learner. api/analytics.py computes the same shape with a db.get(User)
    plus a TopicReadiness select inside a Python loop over students, and the home
    surface then fanned that out per group — eight classes meant eight round
    trips, each internally looping (PERF-1). Here the whole roster is aggregated
    in SQL and folded in Python, so the query count does not grow with the number
    of classes or learners.

    Returns {group_id: (mean_score_or_None, contributing_learner_count)}. A class
    with no confident evidence maps to (None, 0) — never 0.0, which a surface
    would render as a real score (PROD-2).
    """
    if not groups:
        return {}
    group_ids = [g.id for g in groups]

    # Weighted per (group, learner): SUM(weight * score) / SUM(weight), matching
    # the subject-weighted overall analytics computes one student at a time.
    rows = (
        await session.execute(
            select(
                GroupMember.group_id,
                TopicReadiness.student_id,
                func.sum(Topic.weight * TopicReadiness.score),
                func.sum(Topic.weight),
            )
            .select_from(TopicReadiness)
            .join(Topic, Topic.id == TopicReadiness.topic_id)
            .join(GroupMember, GroupMember.student_id == TopicReadiness.student_id)
            .join(Group, Group.id == GroupMember.group_id)
            .where(
                GroupMember.group_id.in_(group_ids),
                # Topics are global, so the subject match is what stops another
                # subject's readiness leaking into this class's number.
                Topic.subject_id == Group.subject_id,
                TopicReadiness.confidence.in_(CONFIDENT),
            )
            .group_by(GroupMember.group_id, TopicReadiness.student_id)
        )
    ).all()

    per_group: dict[int, list[float]] = defaultdict(list)
    for group_id, _student_id, weighted, weight_total in rows:
        if not weight_total:
            continue
        per_group[group_id].append(weighted / weight_total)

    return {
        gid: (
            (round(sum(scores) / len(scores), 1), len(scores))
            if (scores := per_group.get(gid, []))
            else (None, 0)
        )
        for gid in group_ids
    }
