"""Creating and deleting a lesson against the teaching plan (task 6.5, AV-17, E15;
auto-record added in 7.4, AV-119).

Until 7.4 a lesson was never created for the tutor: the plan only suggested and
the tutor submitted. AV-119 deliberately changes that. A class with an accepted
plan *counts as taught*: when a planned lesson's local end has passed and
nobody has recorded or cancelled it, `lesson_autorecord` creates the lesson
through this module's `create_lesson` (so the claim on the slot, the topic
validation and the race rules are one code path, not two). Why: tutors who
taught but never logged left coverage and readiness blind to real teaching, and
the platform could not tell "forgot to log" from "did not happen". Those lessons
carry `origin = plan` so they stay traceable and are labelled as recorded from
the plan (`PROD-1`); the tutor can still edit or delete them.

`lesson_topics` stays the sole source of syllabus coverage (`PROD-14`). A tutor's
lesson writes exactly what the tutor sent; an auto-recorded one writes the
slot's share of its chapter (`teaching_plan.topic_share`).
"""

from datetime import date, time

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Group,
    Lesson,
    LessonMode,
    LessonOrigin,
    LessonTopic,
    PlanSlot,
    PlanSlotProvenance,
    ScheduleSlot,
    TeachingPlan,
    TeachingPlanStatus,
    Topic,
)
from app.models.base import utcnow
from app.services.plan_start_times import slot_has_ended
from app.services.teaching_plan import (
    STARTED_PROVENANCE,
    PlanInputError,
    PlanSlotNotFound,
    PlanStateError,
    note_unrescheduled,
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
    # Lock order, followed by every writer (accept_plan, replan, edit_slot,
    # release_slot_for_lesson): plan rows by id first, then slots. Locking the slot
    # first (or both in planner order, as a join does) deadlocks against a writer
    # holding the plan, so the plan row is taken alone here.
    plan_id = await session.scalar(
        select(TeachingPlan.id)
        .where(
            TeachingPlan.group_id == group.id,
            TeachingPlan.organization_id == group.organization_id,
            TeachingPlan.status == TeachingPlanStatus.accepted,
        )
        .with_for_update()
    )
    if plan_id is None:
        raise PlanSlotNotFound(slot_id)
    slot = await session.scalar(
        select(PlanSlot)
        .where(PlanSlot.id == slot_id, PlanSlot.plan_id == plan_id)
        # Serialises two requests confirming one slot (a no-op on SQLite); the
        # UNIQUE on `lesson_id` is the backstop. `of=` keeps the lock off the plan.
        .with_for_update(of=PlanSlot)
        # Fresh state: callers decide on this row after waiting for its lock.
        .execution_options(populate_existing=True)
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
    mode: LessonMode = LessonMode.in_person,
    start_time: time | None = None,
    origin: LessonOrigin = LessonOrigin.tutor,
    require_slot_date: bool = False,
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
        if slot.cancelled_at is not None:
            raise PlanStateError("That planned lesson was cancelled")
        if slot.lesson_id is not None or slot.provenance in STARTED_PROVENANCE:
            raise PlanStateError("A lesson already covers that planned lesson")

    lesson = Lesson(
        organization_id=group.organization_id,
        group_id=group.id,
        date=lesson_date,
        duration_min=duration_min,
        notes=notes,
        schedule_slot_id=schedule_slot_id,
        mode=mode,
        start_time=start_time,
        origin=origin,
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
                # A cancel that landed after the read above must still win.
                PlanSlot.cancelled_at.is_(None),
                # The auto-record's backstop: a slot moved to another day since
                # it was judged due is not this lesson any more.
                *((PlanSlot.scheduled_date == lesson_date,) if require_slot_date else ()),
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
    plan_id = await session.scalar(select(PlanSlot.plan_id).where(PlanSlot.lesson_id == lesson_id))
    if plan_id is None:
        return
    # The plan row lock first, as `accept_plan` takes it, so the two serialise:
    # an accept that is carrying this link to a new plan finishes (and moves the
    # link) before this clears it, or this finishes before accept reads it.
    await session.scalar(
        select(TeachingPlan.id).where(TeachingPlan.id == plan_id).with_for_update()
    )
    slot = await session.scalar(
        select(PlanSlot)
        .where(PlanSlot.lesson_id == lesson_id)
        .execution_options(populate_existing=True)
    )
    if slot is None:  # accept moved the link while we waited
        return
    lesson = await session.get(Lesson, lesson_id)
    slot.lesson_id = None
    plan = await session.get(TeachingPlan, plan_id, populate_existing=True)
    # Whatever the lesson's origin: a slot whose end has passed and is freed as
    # untaught would be re-recorded by the next sweep, overriding the tutor who
    # just deleted it (`PROD-7`). It is cancelled instead, and noted as not
    # rescheduled so "behind" still reports the gap and a re-plan can catch the
    # content up (AV-119, AV-120). A slot still in the future is freed as before.
    if plan is not None and (
        (lesson is not None and lesson.origin is LessonOrigin.plan)
        or await slot_has_ended(session, slot, plan)
    ):
        slot.cancelled_at = utcnow()
        note_unrescheduled(plan, slot.id)
    slot.provenance = PlanSlotProvenance.manually_modified
    await session.flush()
