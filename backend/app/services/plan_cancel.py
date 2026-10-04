"""Cancelling a planned lesson, and shifting the plan around it (task 7.4, AV-120, E15).

The tutor cancels one lesson of the *accepted* plan. The row is kept with
`cancelled_at` / `cancelled_by_id` (the record of intent, E15); it takes no
share of its chapter's topics and blocks nothing. The plan then shifts on its
own, with no re-plan acceptance: a replacement carrying the cancelled lesson's
chapter goes in immediately after it, and every later not-yet-taught lesson
(the replacement included) moves forward to the next free lesson dates of the
plan's own calendar, each taking the timetable's start time for its new weekday.

If the tail does not fit before the exam nothing moves. The lesson stays
cancelled, the plan records that its content was not rescheduled
(`UNRESCHEDULED_KEY`), and "behind" (`plan_progress`) reports it so the tutor
can re-plan (6.6). Shifting only part of the tail would silently drop the last
lessons off the end of the plan.

Lock order is `plan_lessons._accepted_slot`'s: the plan row, then its slots.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Group, PlanBreak, PlanSlot, PlanSlotProvenance, TeachingPlan, User
from app.models.base import utcnow
from app.services.plan_drafting import _weekdays, renumber_slots
from app.services.plan_lessons import _accepted_slot
from app.services.plan_scheduler import DateRange, available_lesson_dates
from app.services.plan_start_times import class_zone, timetable_start_times
from app.services.plan_timing import slot_end_utc, timetable_default
from app.services.teaching_plan import (
    STARTED_PROVENANCE,
    PlanStateError,
    note_unrescheduled,
)

NO_ROOM_MESSAGE = "No room before the exam — re-plan to catch up"


@dataclass(frozen=True)
class CancelOutcome:
    shifted: bool
    #: Lessons that moved, the replacement included.
    moved: int
    message: str | None = None


def _is_untaught(slot: PlanSlot) -> bool:
    return (
        slot.lesson_id is None
        and slot.provenance not in STARTED_PROVENANCE
        and slot.cancelled_at is None
    )


async def cancel_slot(
    session: AsyncSession,
    *,
    group: Group,
    user: User,
    slot_id: int,
    today: date,
    now: datetime | None = None,
) -> CancelOutcome:
    """Cancel the slot and shift the tail. One transaction."""
    target = await _accepted_slot(session, group, slot_id)
    if target.cancelled_at is not None:
        raise PlanStateError("That lesson is already cancelled")
    if target.lesson_id is not None or target.provenance in STARTED_PROVENANCE:
        raise PlanStateError("A lesson is already recorded for it; delete that lesson instead")

    plan = await session.get(TeachingPlan, target.plan_id, populate_existing=True)
    assert plan is not None  # `_accepted_slot` just resolved it
    slots = list(
        await session.scalars(
            select(PlanSlot)
            .where(PlanSlot.plan_id == plan.id)
            .order_by(PlanSlot.scheduled_date, PlanSlot.sequence, PlanSlot.id)
            .with_for_update(of=PlanSlot)
            .execution_options(populate_existing=True)
        )
    )
    target.cancelled_at = utcnow()
    target.cancelled_by_id = user.id

    position = next(i for i, s in enumerate(slots) if s.id == target.id)
    tail = [s for s in slots[position + 1 :] if _is_untaught(s)]
    moving = {s.id for s in tail}
    # Dates the shift must not land on: every lesson that stays put (earlier ones,
    # and taught ones wherever they sit). The cancelled lesson's own date is free
    # again but the replacement goes strictly after it.
    held = {s.scheduled_date for s in slots if s.cancelled_at is None and s.id not in moving}
    breaks = (await session.scalars(select(PlanBreak).where(PlanBreak.plan_id == plan.id))).all()
    blocked = (
        *(DateRange(b.start_date, b.end_date) for b in breaks),
        *(DateRange(d, d) for d in sorted(held)),
    )
    weekdays = await _weekdays(session, group, plan)
    start = max(target.scheduled_date + timedelta(days=1), today)
    free = available_lesson_dates(start, plan.exam_date, weekdays, blocked)
    start_times = (await timetable_start_times(session, [group.id])).get(group.id, {})
    if free and free[0] == today:
        # A late cancel must not put a lesson on today's date when today's lesson
        # window has already ended (tutor-local): it would be due at once.
        ends = slot_end_utc(
            today,
            timetable_default(start_times, today),
            plan.lesson_minutes,
            await class_zone(session, group.id),
        )
        if ends <= (now or datetime.now(timezone.utc)):
            free = free[1:]

    if len(free) < len(tail) + 1:
        note_unrescheduled(plan, target.id)
        await session.commit()
        return CancelOutcome(shifted=False, moved=0, message=NO_ROOM_MESSAGE)

    replacement = PlanSlot(
        plan_id=plan.id,
        chapter_id=target.chapter_id,
        scheduled_date=free[0],
        sequence=0,
        provenance=PlanSlotProvenance.generated,
        start_time=timetable_default(start_times, free[0]),
    )
    session.add(replacement)
    # Dates move, chapters do not. A tutor-edited (`manually_modified`) lesson
    # keeps its own chapter and its provenance, so the order of what the tutor
    # arranged survives the shift (AV-77); every lesson slides one place later
    # and the replacement fills the first.
    for slot, new_date in zip(tail, free[1:], strict=False):
        old_weekday = slot.scheduled_date.weekday()
        # Consistent with `edit_slot`: an explicit time survives only while the
        # weekday is unchanged; a new weekday takes that day's timetable time.
        if slot.start_time is None or new_date.weekday() != old_weekday:
            slot.start_time = timetable_default(start_times, new_date)
        slot.scheduled_date = new_date
    await session.flush()
    await renumber_slots(session, plan.id)
    await session.commit()
    return CancelOutcome(shifted=True, moved=len(tail) + 1)
