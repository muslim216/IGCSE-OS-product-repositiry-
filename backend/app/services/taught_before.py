"""What a class was taught before it joined Avora (task 9.1b).

A tutor who starts mid-year has already covered part of the syllabus. That is
stored as a marker per (class, topic), not as a fake lesson: a lesson would invent
a date, attendance and a lesson count. It is a second coverage source beside
`lesson_topics`, and every coverage reader unions the two through
`taught_before_topic_ids`.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Group, TaughtBeforeTopic, TeachingPlan, TeachingPlanStatus, User
from app.models.base import utcnow


@dataclass(frozen=True)
class TaughtBefore:
    answered: bool
    answered_at: datetime | None
    topic_ids: list[int]


async def get_taught_before(session: AsyncSession, group: Group) -> TaughtBefore:
    ids = await session.scalars(
        select(TaughtBeforeTopic.topic_id)
        .where(
            TaughtBeforeTopic.group_id == group.id,
            TaughtBeforeTopic.organization_id == group.organization_id,
        )
        .order_by(TaughtBeforeTopic.topic_id)
    )
    return TaughtBefore(
        answered=group.taught_before_answered_at is not None,
        answered_at=group.taught_before_answered_at,
        topic_ids=list(ids),
    )


async def replace_taught_before(
    session: AsyncSession, *, group: Group, user: User, topic_ids: list[int]
) -> TaughtBefore:
    """Set the class's taught-before list to exactly these topics. Replaces rather
    than appends, so a repeat of the same request changes nothing (and an empty
    list means "starting fresh"). Raises `PlanInputError` before writing if a topic
    is not of the class's subject (`SEC-8`).

    Queues no readiness recompute, mirroring lesson-topic edits (`set_lesson_topics`
    queues none): coverage is read at the next recompute.

    A changed list marks the class's plan draft stale: the drafter skipped (or
    kept) chapters according to the old list, so accepting those slots would
    promote a plan built on an answer that no longer holds."""
    # Imported here, not at the top: the coverage readers (readiness, plan drafting)
    # import this module, and plan_lessons reaches plan_drafting through
    # teaching_plan, so a top-level import would be a cycle.
    from app.services.plan_lessons import validated_topic_ids
    from app.services.teaching_plan import mark_draft_stale

    wanted = await validated_topic_ids(session, group, topic_ids)
    # Serialises two saves for one class (a no-op on SQLite): without it both
    # delete, both insert, and the second commit fails the unique constraint.
    await session.scalar(select(Group.id).where(Group.id == group.id).with_for_update())
    before = set(
        await session.scalars(
            select(TaughtBeforeTopic.topic_id).where(
                TaughtBeforeTopic.group_id == group.id,
                TaughtBeforeTopic.organization_id == group.organization_id,
            )
        )
    )
    if before != set(wanted):
        draft = await session.scalar(
            select(TeachingPlan).where(
                TeachingPlan.group_id == group.id,
                TeachingPlan.organization_id == group.organization_id,
                TeachingPlan.status == TeachingPlanStatus.draft,
            )
        )
        if draft is not None:
            mark_draft_stale(draft)
    await session.execute(
        delete(TaughtBeforeTopic).where(
            TaughtBeforeTopic.group_id == group.id,
            TaughtBeforeTopic.organization_id == group.organization_id,
        )
    )
    for topic_id in sorted(wanted):
        session.add(
            TaughtBeforeTopic(
                organization_id=group.organization_id,
                group_id=group.id,
                topic_id=topic_id,
                created_by_id=user.id,
            )
        )
    group.taught_before_answered_at = utcnow()
    await session.commit()
    return await get_taught_before(session, group)


async def answered_group_ids(session: AsyncSession, group_ids: Iterable[int]) -> set[int]:
    """Which of these classes' tutors answered the question (one query)."""
    wanted = set(group_ids)
    if not wanted:
        return set()
    return set(
        await session.scalars(
            select(Group.id).where(
                Group.id.in_(wanted), Group.taught_before_answered_at.is_not(None)
            )
        )
    )


async def taught_before_topic_ids(
    session: AsyncSession, group_ids: Iterable[int], *, topic_ids: Iterable[int] | None = None
) -> set[int]:
    """Union of the taught-before topics of these classes, optionally narrowed to
    `topic_ids`. One query however many classes."""
    wanted = set(group_ids)
    if not wanted:
        return set()
    stmt = select(TaughtBeforeTopic.topic_id).where(TaughtBeforeTopic.group_id.in_(wanted))
    if topic_ids is not None:
        stmt = stmt.where(TaughtBeforeTopic.topic_id.in_(set(topic_ids)))
    return set(await session.scalars(stmt.distinct()))
