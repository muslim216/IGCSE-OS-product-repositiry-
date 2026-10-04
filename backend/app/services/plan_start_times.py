"""The weekly timetable as the source of a planned lesson's default start time
(task 7.4, AV-119), and the one "has this planned lesson ended" rule. Split from
`teaching_plan` so the drafting and reflow jobs, which `teaching_plan` imports,
can use it without a cycle."""

import logging
from collections.abc import Sequence
from datetime import datetime, time, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Group, Organization, PlanSlot, ScheduleSlot, TeachingPlan, User
from app.services.plan_timing import slot_end_utc
from app.services.timezones import effective_timezone, is_valid_timezone

log = logging.getLogger("plan_start_times")


async def timetable_start_times(
    session: AsyncSession, group_ids: Sequence[int]
) -> dict[int, dict[int, time]]:
    """Per class, the weekly timetable's start time for each weekday (task 7.4).
    When several slots share a weekday the earliest wins: a plan holds one lesson
    per date, so the first lesson of the day is the one the plan means."""
    out: dict[int, dict[int, time]] = {}
    if not group_ids:
        return out
    rows = await session.execute(
        select(ScheduleSlot.group_id, ScheduleSlot.weekday, ScheduleSlot.start_time)
        .where(ScheduleSlot.group_id.in_(set(group_ids)))
        .order_by(ScheduleSlot.start_time, ScheduleSlot.id)
    )
    for group_id, weekday, start in rows.all():
        out.setdefault(group_id, {}).setdefault(weekday, start)
    return out


def resolve_zone(user_zone: str | None, org_zone: str | None, group_id: int) -> str | None:
    """The class's effective zone, warning when there is none or it cannot be
    loaded. The caller keeps the UTC fallback (`plan_timing`); the warning is so
    "lessons end at the wrong hour" is traceable to a missing zone (AV-67)."""
    zone = effective_timezone(user_zone, org_zone)
    if zone is None:
        log.warning("class %s has no timezone (user or organization); using UTC", group_id)
    elif not is_valid_timezone(zone):
        log.warning("class %s timezone %r cannot be loaded; using UTC", group_id, zone)
    return zone


async def slot_has_ended(
    session: AsyncSession, slot: PlanSlot, plan: TeachingPlan, now: datetime | None = None
) -> bool:
    """Has this planned lesson's local end passed? Same rule the auto-record uses
    (start, else timetable, else end of the local day)."""
    row = (
        await session.execute(
            select(User.time_zone, Organization.timezone)
            .select_from(Group)
            .join(User, User.id == Group.tutor_id)
            .join(Organization, Organization.id == Group.organization_id)
            .where(Group.id == plan.group_id)
        )
    ).one_or_none()
    zone = resolve_zone(row[0], row[1], plan.group_id) if row else None
    by_weekday = (await timetable_start_times(session, [plan.group_id])).get(plan.group_id, {})
    start = (
        slot.start_time
        if slot.start_time is not None
        else by_weekday.get(slot.scheduled_date.weekday())
    )
    end = slot_end_utc(slot.scheduled_date, start, plan.lesson_minutes, zone)
    return end <= (now or datetime.now(timezone.utc))
