"""Is a class behind its teaching plan? (task 6.6, AV-18)

Behind means: slots of the *accepted* plan dated before the tutor's today that
no lesson has been recorded against. Nothing here reschedules anything; it only
reports the gap, and the tutor decides what to do about it (the re-plan waits
for acceptance, see `plan_replan`).

"Not recorded" is the honest word. A lesson may have been taught and never
logged, and the platform cannot tell those apart, so nothing here says "missed"
to a tutor or blames them for it (PROD-2: the fact is the absence of a record).
A class with no accepted plan is never behind, and a draft is never read
(`TeachingPlan.status == accepted`, task 6.4).
"""

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
from app.services.teaching_plan import STARTED_PROVENANCE
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


def compute_progress(slots: Iterable[SlotFact], today: date) -> Progress:
    """The gap between plan and record. Today's own slot is never counted: the
    day is not over, so a lesson not yet recorded is not yet a gap."""
    past = [s for s in slots if s.scheduled_date < today]
    untaught = sorted(
        (s for s in past if not is_taught(s)),
        key=lambda s: (s.scheduled_date, s.sequence, s.slot_id),
    )
    first = untaught[0] if untaught else None
    return Progress(
        planned_to_date=len(past),
        taught_to_date=len(past) - len(untaught),
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
) -> dict[int, tuple[str, Progress]]:
    """(class name, progress) for the tutor's classes whose accepted plan has at
    least one lesson dated before today; one query however many classes
    (`PERF-1`). Organization and tutor come from the user (`SEC-7`), never from
    the request. `group_id` narrows it to one class. `own_classes_only=False` is
    for a class the caller has already been authorised for (an admin viewing a
    tutor's class); the organization filter still binds."""
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
        )
        .select_from(PlanSlot)
        .join(TeachingPlan, TeachingPlan.id == PlanSlot.plan_id)
        .join(Group, Group.id == TeachingPlan.group_id)
        .join(Chapter, Chapter.id == PlanSlot.chapter_id)
        .where(
            TeachingPlan.organization_id == user.organization_id,
            # Nothing reads a draft plan (task 6.4).
            TeachingPlan.status == TeachingPlanStatus.accepted,
            PlanSlot.scheduled_date < today,
        )
    )
    if own_classes_only:
        query = query.where(Group.tutor_id == user.id)
    if group_id is not None:
        query = query.where(Group.id == group_id)
    names: dict[int, str] = {}
    facts: dict[int, list[SlotFact]] = defaultdict(list)
    for gid, name, sid, day, seq, prov, lesson_id, cid, code, title in (
        await db.execute(query)
    ).all():
        names[gid] = name
        facts[gid].append(SlotFact(day, seq, sid, cid, code, title, lesson_id is not None, prov))
    return {gid: (names[gid], compute_progress(rows, today)) for gid, rows in facts.items()}
