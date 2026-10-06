"""The in-app reminder for an upcoming planned lesson (task 7.4, AV-120).

Computed from plan slots at read time: there is no notifications table (owner
decision, 2026-10-04; email and push are Phase 8). From fifteen minutes before a
planned lesson starts until it ends, the tutor sees what the plan says it
covers and can review (open the record form pre-filled) or cancel it. After the
end the auto-record has taken it, so the reminder is gone.

A lesson with no start time (its own, then the timetable's) can never have a
reminder: there is no moment to remind at, and midnight is not a guess we make
(`DB-9`). Only the tutor's own classes, only the accepted plan, only a lesson
nobody has recorded or cancelled.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Chapter,
    Group,
    Organization,
    PlanSlot,
    TeachingPlan,
    TeachingPlanStatus,
    Topic,
    User,
)
from app.services.plan_start_times import timetable_start_times
from app.services.plan_timing import reminder_window_open, slot_end_utc, slot_start_utc
from app.services.teaching_plan import STARTED_PROVENANCE, effective_start_time, topic_share
from app.services.timezones import effective_timezone


@dataclass(frozen=True)
class LessonReminder:
    slot_id: int
    group_id: int
    group_name: str
    scheduled_date: date
    start_time: time
    starts_at: datetime
    chapter: Chapter
    topics: list[Topic]


def _tz(name: str | None) -> ZoneInfo | timezone:
    if name:
        try:
            return ZoneInfo(name)
        except Exception:  # noqa: BLE001 - degrade to UTC like `timezones.now_in`
            pass
    return timezone.utc


async def due_reminders(
    session: AsyncSession, user: User, now: datetime | None = None
) -> list[LessonReminder]:
    now = now or datetime.now(timezone.utc)
    org = await session.get(Organization, user.organization_id)
    zone = effective_timezone(user.time_zone, org.timezone if org else None)
    local_today = now.astimezone(_tz(zone)).date()
    rows = (
        await session.execute(
            select(PlanSlot, TeachingPlan, Group, Chapter)
            .join(TeachingPlan, TeachingPlan.id == PlanSlot.plan_id)
            .join(Group, Group.id == TeachingPlan.group_id)
            .join(Chapter, Chapter.id == PlanSlot.chapter_id)
            .where(
                # Organization and tutor from the user, never the request (`SEC-7`).
                TeachingPlan.organization_id == user.organization_id,
                Group.organization_id == user.organization_id,
                Group.tutor_id == user.id,
                Group.deleted_at.is_(None),
                TeachingPlan.status == TeachingPlanStatus.accepted,
                PlanSlot.lesson_id.is_(None),
                PlanSlot.provenance.not_in(STARTED_PROVENANCE),
                PlanSlot.cancelled_at.is_(None),
                PlanSlot.scheduled_date.between(
                    local_today - timedelta(days=1), local_today + timedelta(days=1)
                ),
            )
            .order_by(PlanSlot.scheduled_date, PlanSlot.sequence, PlanSlot.id)
        )
    ).all()
    timetables = await timetable_start_times(session, list({g.id for _, _, g, _ in rows}))
    out: list[LessonReminder] = []
    for slot, plan, group, chapter in rows:
        start = effective_start_time(
            slot.start_time, timetables.get(group.id, {}), slot.scheduled_date
        )
        if start is None:
            continue
        starts_at = slot_start_utc(slot.scheduled_date, start, zone)
        ends_at = slot_end_utc(slot.scheduled_date, start, plan.lesson_minutes, zone)
        if starts_at is None or not reminder_window_open(starts_at, ends_at, now):
            continue
        topics = await topic_share(session, plan_id=plan.id, slot=slot, chapter=chapter)
        out.append(
            LessonReminder(
                slot_id=slot.id,
                group_id=group.id,
                group_name=group.name,
                scheduled_date=slot.scheduled_date,
                start_time=start,
                starts_at=starts_at,
                chapter=chapter,
                topics=topics,
            )
        )
    return out
