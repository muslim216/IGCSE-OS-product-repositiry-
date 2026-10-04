"""A class with an accepted plan counts as taught (task 7.4, AV-119, E15).

A self-rescheduling sweep finds planned lessons of *accepted* plans that nobody
recorded or cancelled and whose local end has passed, and records each one
through `plan_lessons.create_lesson` with `origin = plan`: a real `Lesson`, its
`LessonTopic` rows (the slot's share of its chapter), and the slot claimed. Why
this exists is in `plan_lessons`' module docstring. A draft plan is never read
(`TeachingPlanStatus.accepted`, task 6.4), and a plan that went live *after* a
lesson's end never records it: those lessons were never the tutor's agreed plan,
and recording them would turn every pre-existing gap into taught teaching.

Reliability follows `narrative.py`: the successor sweep is committed in its own
transaction *before* the work, so a failing run cannot stop the schedule, and
`ensure_lesson_autorecord_scheduled` heals a lost row at startup.

Safe to re-run and to race the tutor (`BE-6`): the slot is claimed by one
conditional UPDATE inside `create_lesson` and `plan_slots.lesson_id` is UNIQUE,
so a re-run, an overlapping sweep or a tutor submitting the same lesson at the
same moment produces exactly one lesson; the loser is rolled back and skipped.
Each slot is its own transaction, so one failure never costs the others.
"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import Date, cast, func, literal_column, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import async_session
from app.models import (
    Chapter,
    Group,
    Job,
    JobStatus,
    LessonMode,
    LessonOrigin,
    Organization,
    PlanSlot,
    TeachingPlan,
    TeachingPlanStatus,
    User,
)
from app.services import plan_lessons
from app.services.plan_start_times import resolve_zone, slot_has_ended, timetable_start_times
from app.services.plan_timing import slot_end_utc
from app.services.teaching_plan import (
    STARTED_PROVENANCE,
    PlanSlotNotFound,
    PlanStateError,
    effective_start_time,
    topic_share,
)
from app.workers.jobs import enqueue

log = logging.getLogger("lesson_autorecord")

SWEEP_JOB = "autorecord_planned_lessons"

#: One sweep records at most this many, oldest first. The first run against an
#: established installation drains over several cycles instead of one long burst.
MAX_PER_SWEEP = 200


def _aware(value: datetime) -> datetime:
    # SQLite (the test database) hands back naive datetimes; they are UTC.
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


#: A slot that raised is skipped for this many sweeps, so a permanently failing
#: slot cannot starve the batch or fill the log every cycle. In-process on
#: purpose: a restart simply tries it again.
FAILURE_BACKOFF_SWEEPS = 8
_sweep_counter = 0
_failed_at: dict[int, int] = {}


def _accepted_lower_bound(session: AsyncSession):
    """SQL for "the day before the plan was accepted", the earliest a slot that
    ended after acceptance can be dated (a local date is at most a day from the
    UTC date). Pushes the pre-acceptance exclusion into the query, so those old
    gaps are never fetched again each sweep and never fill the batch."""
    if session.bind is not None and session.bind.dialect.name == "sqlite":
        return func.date(TeachingPlan.accepted_at, "-1 day")
    return cast(TeachingPlan.accepted_at - literal_column("interval '1 day'"), Date)


async def due_slot_ids(session: AsyncSession, now: datetime) -> list[int]:
    """Slots of accepted plans whose lesson has ended and nobody has recorded or
    cancelled, oldest first. The local end is decided per class in the tutor's
    own zone (override, else the organization's), never the server's."""
    rows = (
        await session.execute(
            select(
                PlanSlot.id,
                PlanSlot.scheduled_date,
                PlanSlot.start_time,
                TeachingPlan.lesson_minutes,
                TeachingPlan.accepted_at,
                Group.id,
                User.time_zone,
                Organization.timezone,
            )
            .join(TeachingPlan, TeachingPlan.id == PlanSlot.plan_id)
            .join(Group, Group.id == TeachingPlan.group_id)
            .join(Organization, Organization.id == TeachingPlan.organization_id)
            .join(User, User.id == Group.tutor_id)
            .where(
                TeachingPlan.status == TeachingPlanStatus.accepted,
                PlanSlot.lesson_id.is_(None),
                PlanSlot.provenance.not_in(STARTED_PROVENANCE),
                PlanSlot.cancelled_at.is_(None),
                # Bounds the scan; the zone offset is at most a day either way.
                PlanSlot.scheduled_date <= now.date() + timedelta(days=1),
                PlanSlot.scheduled_date >= _accepted_lower_bound(session),
            )
            .order_by(PlanSlot.scheduled_date, PlanSlot.sequence, PlanSlot.id)
            .limit(MAX_PER_SWEEP * 4)
        )
    ).all()
    timetables = await timetable_start_times(session, list({r[5] for r in rows}))
    zones: dict[int, str | None] = {}
    due: list[int] = []
    for slot_id, day, start, minutes, accepted_at, group_id, user_zone, org_zone in rows:
        if (
            _sweep_counter - _failed_at.get(slot_id, -FAILURE_BACKOFF_SWEEPS)
            < FAILURE_BACKOFF_SWEEPS
        ):
            continue
        if group_id not in zones:  # warns once per class per sweep
            zones[group_id] = resolve_zone(user_zone, org_zone, group_id)
        start = effective_start_time(start, timetables.get(group_id, {}), day)
        end = slot_end_utc(day, start, minutes, zones[group_id])
        if end > now:
            continue
        if accepted_at is not None and end <= _aware(accepted_at):
            continue  # ended before the tutor accepted this plan (exact check)
        due.append(slot_id)
        if len(due) >= MAX_PER_SWEEP:
            break
    return due


async def record_planned_lesson(session: AsyncSession, slot_id: int, *, now: datetime) -> bool:
    """Record one due slot as a lesson. True when this call created it; False
    when it no longer applies (recorded, cancelled, moved, plan replaced, or lost
    the race to the tutor).

    Decided on locked state, never on the sweep's listing: the plan row is locked
    first (`_accepted_slot`'s order) and the slot re-read under that lock, so a
    tutor's cancel, move or recording that landed since is seen. Every False
    after the lock is taken rolls back, releasing the locks at once.
    """
    ids = (
        await session.execute(
            select(TeachingPlan.group_id, PlanSlot.id)
            .join(PlanSlot, PlanSlot.plan_id == TeachingPlan.id)
            .where(PlanSlot.id == slot_id, TeachingPlan.status == TeachingPlanStatus.accepted)
        )
    ).one_or_none()
    if ids is None:
        return False
    group = await session.get(Group, ids[0], populate_existing=True)
    if group is None:
        return False
    try:
        slot = await plan_lessons._accepted_slot(session, group, slot_id)
    except PlanSlotNotFound:
        await session.rollback()
        return False
    plan = await session.get(TeachingPlan, slot.plan_id, populate_existing=True)
    if (
        plan is None
        or slot.lesson_id is not None
        or slot.provenance in STARTED_PROVENANCE
        or slot.cancelled_at is not None
        or not await slot_has_ended(session, slot, plan, now)
    ):
        await session.rollback()
        return False
    by_weekday = (await timetable_start_times(session, [group.id])).get(group.id, {})
    start = effective_start_time(slot.start_time, by_weekday, slot.scheduled_date)
    chapter = await session.get(Chapter, slot.chapter_id)
    topics = (
        await topic_share(session, plan_id=plan.id, slot=slot, chapter=chapter) if chapter else []
    )
    try:
        await plan_lessons.create_lesson(
            session,
            group=group,
            lesson_date=slot.scheduled_date,
            duration_min=plan.lesson_minutes,
            notes=None,
            schedule_slot_id=None,
            topic_ids=[t.id for t in topics],
            plan_slot_id=slot.id,
            mode=LessonMode.in_person,
            start_time=start,
            origin=LessonOrigin.plan,
            require_slot_date=True,
        )
    except (PlanStateError, PlanSlotNotFound):
        # The tutor (or another sweep) took the slot first: exactly one lesson.
        await session.rollback()
        return False
    return True


async def sweep_planned_lessons(session: AsyncSession, payload: dict) -> None:
    """Job handler. The successor is committed first so the schedule survives any
    outcome of the work; the kill switch only skips the work."""
    await _commit_successor_sweep()
    if not get_settings().lesson_autorecord_enabled:
        return
    now = datetime.now(timezone.utc)
    recorded = 0
    global _sweep_counter
    _sweep_counter += 1
    for slot_id in await due_slot_ids(session, now):
        try:
            if await record_planned_lesson(session, slot_id, now=now):
                recorded += 1
        except Exception:  # noqa: BLE001 - one bad slot must not cost the rest
            await session.rollback()
            _failed_at[slot_id] = _sweep_counter
            log.exception(
                "could not auto-record planned lesson %s; skipping it for %s sweeps",
                slot_id,
                FAILURE_BACKOFF_SWEEPS,
            )
    if recorded:
        log.info("auto-recorded %s planned lessons", recorded)


async def _has_pending(session: AsyncSession) -> bool:
    return (
        await session.scalar(
            select(Job.id).where(Job.type == SWEEP_JOB, Job.status == JobStatus.pending).limit(1)
        )
    ) is not None


async def ensure_lesson_autorecord_scheduled(session: AsyncSession) -> None:
    """Startup floor: schedule a sweep if none is pending. Idempotent."""
    if await _has_pending(session):
        return
    await enqueue(session, SWEEP_JOB, {})


async def _commit_successor_sweep() -> None:
    """Queue the next sweep in its own committed transaction (see `narrative`)."""
    async with async_session() as session:
        if await _has_pending(session):
            return
        interval = get_settings().lesson_autorecord_interval_minutes
        await enqueue(
            session,
            SWEEP_JOB,
            {},
            run_after=datetime.now(timezone.utc) + timedelta(minutes=interval),
        )
        await session.commit()
