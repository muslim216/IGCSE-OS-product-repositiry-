"""Is a class behind its teaching plan? (task 6.6, AV-18; revisited in 7.4, AV-119)

Behind means two things about the *accepted* plan, and nothing here reschedules
anything; it only reports the gap and the tutor decides (re-plan, `plan_replan`):

1. A cancelled lesson whose content could not be rescheduled (there was no room
   before the exam, `plan_cancel`). A cancelled lesson that *was* rescheduled is
   not behind: its replacement is an ordinary slot.
2. A planned lesson dated before the tutor's today that no lesson has been
   recorded against. Since 7.4 the auto-record sweep records every ended lesson
   of an accepted plan, so this should only ever be the sweep's lag. A lesson
   whose end passed less than one sweep interval ago is therefore not counted:
   the sweep has not had its turn yet and nothing is missing.

"Not recorded" is the honest word. The platform cannot tell a lesson that was
taught and never logged from one that did not happen, and nothing here says
"missed" to a tutor or blames them for it (PROD-2: the fact is the absence of a
record). A class with no accepted plan is never behind, and a draft is never
read (`TeachingPlan.status == accepted`, task 6.4).
"""

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import (
    Chapter,
    Group,
    Organization,
    PlanSlot,
    PlanSlotProvenance,
    TeachingPlan,
    TeachingPlanStatus,
    User,
)
from app.services.plan_start_times import resolve_zone, timetable_start_times
from app.services.plan_timing import slot_end_utc
from app.services.teaching_plan import (
    STARTED_PROVENANCE,
    UNRESCHEDULED_KEY,
    effective_start_time,
)
from app.services.timezones import effective_timezone, now_in


@dataclass(frozen=True)
class SlotFact:
    """One planned lesson, as plain values (`BE-4`)."""

    scheduled_date: date
    sequence: int
    slot_id: int
    chapter_id: int
    chapter_code: str
    chapter_title: str
    has_lesson: bool
    provenance: PlanSlotProvenance
    #: When the lesson's local end passes; None = unknown (no lag grace applies).
    ends_at: datetime | None = None
    cancelled: bool = False
    #: A cancelled lesson whose content was not rescheduled (`plan_cancel`).
    unrescheduled: bool = False


@dataclass(frozen=True)
class Progress:
    #: Planned lessons dated before today.
    planned_to_date: int
    #: Of those, the ones a lesson has been recorded against (or marked taught).
    taught_to_date: int
    #: Planned lessons before today with no lesson recorded.
    missed: int
    earliest_missed_date: date | None
    earliest_missed_chapter: tuple[int, str, str] | None  # (id, code, title)


NO_PROGRESS = Progress(0, 0, 0, None, None)


def is_taught(slot: SlotFact) -> bool:
    # Both signals, as `next_unstarted_slot` does: 6.8 may mark a slot taught
    # without a lesson row, and a NULL `lesson_id` alone is not "untaught".
    return slot.has_lesson or slot.provenance in STARTED_PROVENANCE


def compute_progress(
    slots: Iterable[SlotFact],
    today: date,
    now: datetime | None = None,
    grace: timedelta = timedelta(0),
) -> Progress:
    """The gap between plan and record. Today's own slot is never counted: the
    day is not over, so a lesson not yet recorded is not yet a gap. A cancelled
    lesson counts only when its content was not rescheduled, whatever its date.
    With `now`, a lesson that ended less than `grace` ago is the auto-record's
    lag and is not counted either."""
    considered = [
        s
        for s in slots
        if (s.cancelled and s.unrescheduled) or (not s.cancelled and s.scheduled_date < today)
    ]

    def in_lag(s: SlotFact) -> bool:
        # Only an ended-but-unrecorded lesson can be the sweep's lag; a cancelled
        # one is waiting on the tutor, not on the sweep.
        return (
            not s.cancelled
            and now is not None
            and s.ends_at is not None
            and s.ends_at > now - grace
        )

    untaught = sorted(
        (s for s in considered if not is_taught(s) and not in_lag(s)),
        key=lambda s: (s.scheduled_date, s.sequence, s.slot_id),
    )
    lagging = sum(1 for s in considered if not is_taught(s) and in_lag(s))
    first = untaught[0] if untaught else None
    return Progress(
        planned_to_date=len(considered) - lagging,
        taught_to_date=len(considered) - len(untaught) - lagging,
        missed=len(untaught),
        earliest_missed_date=first.scheduled_date if first else None,
        earliest_missed_chapter=(
            (first.chapter_id, first.chapter_code, first.chapter_title) if first else None
        ),
    )


async def tutor_today(db: AsyncSession, user: User) -> date:
    org = await db.get(Organization, user.organization_id)
    return now_in(effective_timezone(user.time_zone, org.timezone if org else None)).date()


async def class_progress(
    db: AsyncSession,
    user: User,
    today: date,
    group_id: int | None = None,
    *,
    own_classes_only: bool = True,
    now: datetime | None = None,
) -> dict[int, tuple[str, Progress]]:
    """(class name, progress) for the tutor's classes whose accepted plan has at
    least one lesson dated before today; one query however many classes
    (`PERF-1`). Organization and tutor come from the user (`SEC-7`), never from
    the request. `group_id` narrows it to one class. `own_classes_only=False` is
    for a class the caller has already been authorised for (an admin viewing a
    tutor's class); the organization filter still binds. `now` pins the clock for tests."""
    query = (
        select(
            Group.id,
            Group.name,
            PlanSlot.id,
            PlanSlot.scheduled_date,
            PlanSlot.sequence,
            PlanSlot.provenance,
            PlanSlot.lesson_id,
            Chapter.id,
            Chapter.code,
            Chapter.title,
            PlanSlot.start_time,
            PlanSlot.cancelled_at,
            TeachingPlan.lesson_minutes,
            TeachingPlan.draft_result,
            User.time_zone,
            Organization.timezone,
        )
        .select_from(PlanSlot)
        .join(TeachingPlan, TeachingPlan.id == PlanSlot.plan_id)
        .join(Group, Group.id == TeachingPlan.group_id)
        .join(Chapter, Chapter.id == PlanSlot.chapter_id)
        .join(User, User.id == Group.tutor_id)
        .join(Organization, Organization.id == TeachingPlan.organization_id)
        .where(
            TeachingPlan.organization_id == user.organization_id,
            # Nothing reads a draft plan (task 6.4).
            TeachingPlan.status == TeachingPlanStatus.accepted,
            # Past lessons, and any cancelled one (whether its content was
            # rescheduled is decided below, whatever its date).
            or_(PlanSlot.scheduled_date < today, PlanSlot.cancelled_at.is_not(None)),
        )
    )
    if own_classes_only:
        query = query.where(Group.tutor_id == user.id)
    if group_id is not None:
        query = query.where(Group.id == group_id)
    rows = (await db.execute(query)).all()
    # Each class's zone comes from its own tutor, as the auto-record sweep decides
    # it, not from whoever is looking (an admin in another zone would otherwise
    # see a different "behind" than the tutor).
    zones: dict[int, str | None] = {}
    timetables = await timetable_start_times(db, list({r[0] for r in rows}))
    now = now or datetime.now(timezone.utc)
    names: dict[int, str] = {}
    facts: dict[int, list[SlotFact]] = defaultdict(list)
    for (
        gid,
        name,
        sid,
        day,
        seq,
        prov,
        lesson_id,
        cid,
        code,
        title,
        start,
        cancelled_at,
        minutes,
        result,
        tz_user,
        tz_org,
    ) in rows:
        names[gid] = name
        if gid not in zones:
            zones[gid] = resolve_zone(tz_user, tz_org, gid)
        start = effective_start_time(start, timetables.get(gid, {}), day)
        unrescheduled = sid in ((result or {}).get(UNRESCHEDULED_KEY) or [])
        facts[gid].append(
            SlotFact(
                day,
                seq,
                sid,
                cid,
                code,
                title,
                lesson_id is not None,
                prov,
                ends_at=slot_end_utc(day, start, minutes, zones[gid]),
                cancelled=cancelled_at is not None,
                unrescheduled=unrescheduled,
            )
        )
    grace = timedelta(minutes=get_settings().lesson_autorecord_interval_minutes)
    return {
        gid: (names[gid], compute_progress(rows_, today, now, grace))
        for gid, rows_ in facts.items()
    }
