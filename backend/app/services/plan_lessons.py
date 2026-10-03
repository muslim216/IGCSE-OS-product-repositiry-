"""Creating and deleting a lesson against the teaching plan (task 6.5, AV-17, E15).

A lesson is never created for the tutor: the plan only suggests, the tutor
submits. When they keep the suggestion the lesson confirms its slot, in the
same transaction. `lesson_topics` stays the sole source of syllabus coverage
(`PROD-14`), written from exactly what the tutor sent and never from the plan.
"""

from datetime import date

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Group,
    Lesson,
    LessonTopic,
    PlanSlot,
    PlanSlotProvenance,
    ScheduleSlot,
    TeachingPlan,
    TeachingPlanStatus,
    Topic,
)
from app.services.teaching_plan import (
    STARTED_PROVENANCE,
    PlanInputError,
    PlanSlotNotFound,
    PlanStateError,
)


class ScheduleSlotNotFound(LookupError):
    """No such weekly timetable slot on this class. The router turns it into a 404 (`API-7`)."""


async def validated_topic_ids(
    session: AsyncSession, group: Group, topic_ids: list[int]
) -> set[int]:
    """The ids as a set, only if every one is a topic of the class's subject.
    Subjects are global but topics are not interchangeable across them, so a
    foreign id must not become coverage (`SEC-8`, `PROD-14`). Shared by create
    and by replacing a lesson's topics, so the two cannot drift."""
    wanted = set(topic_ids)
    if wanted:
        valid = set(
            await session.scalars(
                select(Topic.id).where(Topic.id.in_(wanted), Topic.subject_id == group.subject_id)
            )
        )
        if valid != wanted:
            raise PlanInputError("A topic is not part of this class's subject")
    return wanted


async def replace_lesson_topics(
    session: AsyncSession, *, group: Group, lesson: Lesson, topic_ids: list[int]
) -> None:
    """Replace the lesson's topics with exactly these. Validates before writing."""
    wanted = await validated_topic_ids(session, group, topic_ids)
    for row in await session.scalars(select(LessonTopic).where(LessonTopic.lesson_id == lesson.id)):
        await session.delete(row)
    await session.flush()
    for topic_id in sorted(wanted):
        session.add(LessonTopic(lesson_id=lesson.id, topic_id=topic_id))
    await session.commit()


async def _accepted_slot(session: AsyncSession, group: Group, slot_id: int) -> PlanSlot:
    """The slot, only if it sits on this class's *accepted* plan. A draft's slot,
    another class's and another organization's all look the same: not found."""
    slot = await session.scalar(
        select(PlanSlot)
        .join(TeachingPlan, TeachingPlan.id == PlanSlot.plan_id)
        .where(
            PlanSlot.id == slot_id,
            TeachingPlan.group_id == group.id,
            TeachingPlan.organization_id == group.organization_id,
            TeachingPlan.status == TeachingPlanStatus.accepted,
        )
        # Serialises two requests confirming one slot (a no-op on SQLite); the
        # UNIQUE on `lesson_id` is the backstop.
        .with_for_update()
    )
    if slot is None:
        raise PlanSlotNotFound(slot_id)
    return slot


async def create_lesson(
    session: AsyncSession,
    *,
    group: Group,
    lesson_date: date,
    duration_min: int,
    notes: str | None,
    schedule_slot_id: int | None,
    topic_ids: list[int],
    plan_slot_id: int | None,
) -> Lesson:
    """Create the lesson, its topics, and (when given) confirm the plan slot.

    One transaction: a refused slot means no lesson, so a lesson is never
    half-confirmed.
    """
    wanted = await validated_topic_ids(session, group, topic_ids)
    if schedule_slot_id is not None:
        # Same class only: a timetable slot of another class or organization
        # must not be attachable by guessing its id.
        owned = await session.scalar(
            select(ScheduleSlot.id).where(
                ScheduleSlot.id == schedule_slot_id, ScheduleSlot.group_id == group.id
            )
        )
        if owned is None:
            raise ScheduleSlotNotFound(schedule_slot_id)
    slot = None
    if plan_slot_id is not None:
        slot = await _accepted_slot(session, group, plan_slot_id)
        if slot.lesson_id is not None or slot.provenance in STARTED_PROVENANCE:
            raise PlanStateError("A lesson already covers that planned lesson")

    lesson = Lesson(
        organization_id=group.organization_id,
        group_id=group.id,
        date=lesson_date,
        duration_min=duration_min,
        notes=notes,
        schedule_slot_id=schedule_slot_id,
    )
    session.add(lesson)
    await session.flush()
    for topic_id in sorted(wanted):
        session.add(LessonTopic(lesson_id=lesson.id, topic_id=topic_id))
    if slot is not None:
        # Claimed in one conditional UPDATE, not by writing the instance read
        # above: that read can be stale by now (and the row lock is a no-op on
        # SQLite). Zero rows means someone else took the slot; the lesson made
        # above is rolled back with it.
        claimed = await session.execute(
            update(PlanSlot)
            .where(
                PlanSlot.id == slot.id,
                PlanSlot.lesson_id.is_(None),
                PlanSlot.provenance.not_in(STARTED_PROVENANCE),
            )
            .values(lesson_id=lesson.id, provenance=PlanSlotProvenance.confirmed)
            .execution_options(synchronize_session=False)
        )
        if claimed.rowcount != 1:  # type: ignore[attr-defined]
            await session.rollback()
            raise PlanStateError("A lesson already covers that planned lesson")
    try:
        await session.commit()
    except IntegrityError as exc:  # lost the race for the slot (UNIQUE lesson_id)
        await session.rollback()
        if slot is None:
            raise
        raise PlanStateError("A lesson already covers that planned lesson") from exc
    await session.refresh(lesson)
    return lesson


async def release_slot_for_lesson(session: AsyncSession, lesson_id: int) -> None:
    """Free the plan slot a lesson confirmed, before the lesson is deleted.

    Done here as well as by the FK's ON DELETE SET NULL because SQLite (the test
    database) does not enforce it. Provenance goes to `manually_modified`, not
    back to `generated`: the tutor has touched this slot, and 6.8's reflow must
    not treat it as generator-made and move it (AV-77). Does not commit.
    """
    slot = await session.scalar(select(PlanSlot).where(PlanSlot.lesson_id == lesson_id))
    if slot is None:
        return
    slot.lesson_id = None
    slot.provenance = PlanSlotProvenance.manually_modified
    await session.flush()
