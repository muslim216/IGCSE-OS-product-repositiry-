"""Teaching-plan inputs (task 6.2, AV-15): exam date, pace, past-paper start, breaks.

Everything here mirrors the 6.1 CHECK constraints as explicit validation so a bad
value is a 422 from the API rather than an IntegrityError 500.
"""

from collections import Counter
from dataclasses import dataclass
from datetime import date

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    Chapter,
    Group,
    GroupMember,
    Job,
    JobStatus,
    PlanBreak,
    PlanSlot,
    PlanSlotProvenance,
    ScheduleSlot,
    TeachingPlan,
    TeachingPlanStatus,
    User,
)
from app.models.base import utcnow
from app.schemas.teaching_plan import (
    LESSON_MINUTES_RANGE,
    LESSONS_PER_WEEK_RANGE,
    ChapterReasonOut,
    DraftOutcomeOut,
    PlanBreakOut,
    PlanInputsOut,
    PlanSlotOut,
)
from app.services.plan_drafting import PLAN_DRAFT_JOB, enqueue_plan_draft, renumber_slots
from app.services.readiness_v2_ai import enqueue_readiness_v2_debounced


class PlanInputError(ValueError):
    """An input the plan cannot hold. The router turns it into a 422."""


class PlanStateError(ValueError):
    """The plan is not in a state that allows this. The router turns it into a 409."""


class PlanSlotNotFound(LookupError):
    """No such slot for this class. The router turns it into a 404 (`API-7`)."""


@dataclass(frozen=True)
class TimetableDefaults:
    lessons_per_week: int | None
    lesson_minutes: int | None


async def _plan_with_status(
    session: AsyncSession, group_id: int, status: TeachingPlanStatus
) -> TeachingPlan | None:
    return await session.scalar(
        select(TeachingPlan)
        .where(TeachingPlan.group_id == group_id, TeachingPlan.status == status)
        .options(selectinload(TeachingPlan.breaks))
    )


async def accepted_plan_for_group(session: AsyncSession, group_id: int) -> TeachingPlan | None:
    """The one reader that enforces "nothing reads a draft plan" (task 6.4).

    Anything that consumes a plan (lesson briefs, readiness, the calendar) goes
    through this rather than querying `TeachingPlan` itself.
    """
    return await _plan_with_status(session, group_id, TeachingPlanStatus.accepted)


async def draft_plan_for_group(session: AsyncSession, group_id: int) -> TeachingPlan | None:
    return await _plan_with_status(session, group_id, TeachingPlanStatus.draft)


async def timetable_defaults(session: AsyncSession, group_id: int) -> TimetableDefaults:
    """Pace pre-filled from the class's weekly timetable (owner decision 2026-10-03).

    Lessons per week is the number of slots; length is the most common slot
    duration. When durations differ and tie, the longest wins — better to
    over-allow a lesson than to plan one that cannot cover its chapter. No slots
    means nothing is pre-filled, never 0.
    """
    durations = list(
        await session.scalars(
            select(ScheduleSlot.duration_min).where(ScheduleSlot.group_id == group_id)
        )
    )
    if not durations:
        return TimetableDefaults(None, None)
    counts = Counter(durations)
    top = max(counts.values())
    return TimetableDefaults(len(durations), max(d for d, c in counts.items() if c == top))


def validate_inputs(
    exam_date: date,
    lessons_per_week: int,
    lesson_minutes: int,
    past_paper_start_date: date | None,
    *,
    today: date | None = None,
) -> None:
    today = today or date.today()
    lo, hi = LESSONS_PER_WEEK_RANGE
    if not lo <= lessons_per_week <= hi:
        raise PlanInputError(f"Lessons per week must be between {lo} and {hi}")
    lo, hi = LESSON_MINUTES_RANGE
    if not lo <= lesson_minutes <= hi:
        raise PlanInputError(f"Lesson length must be between {lo} and {hi} minutes")
    if exam_date <= today:
        raise PlanInputError("The exam date must be in the future")
    if past_paper_start_date is not None and past_paper_start_date > exam_date:
        raise PlanInputError("Past papers cannot start after the exam date")


async def save_plan_inputs(
    session: AsyncSession,
    *,
    organization_id: int,
    group_id: int,
    exam_date: date,
    lessons_per_week: int,
    lesson_minutes: int,
    past_paper_start_date: date | None,
    today: date | None = None,
) -> TeachingPlan:
    """Create or update the class's draft. An accepted plan is never touched here:
    changing a live plan's inputs is a re-plan (task 6.6)."""
    validate_inputs(exam_date, lessons_per_week, lesson_minutes, past_paper_start_date, today=today)
    plan = await draft_plan_for_group(session, group_id)
    if plan is None:
        plan = TeachingPlan(
            organization_id=organization_id,
            group_id=group_id,
            status=TeachingPlanStatus.draft,
            exam_date=exam_date,
            lessons_per_week=lessons_per_week,
            lesson_minutes=lesson_minutes,
            past_paper_start_date=past_paper_start_date,
        )
        # A draft drafted beside a live plan keeps its holidays, otherwise
        # changing the exam date would silently drop them.
        accepted = await accepted_plan_for_group(session, group_id)
        if accepted is not None:
            plan.breaks = [
                PlanBreak(start_date=b.start_date, end_date=b.end_date, label=b.label)
                for b in accepted.breaks
            ]
        try:
            # A savepoint, so losing the race to a concurrent save (UNIQUE on
            # group_id + status) rolls back only this insert.
            async with session.begin_nested():
                session.add(plan)
        except IntegrityError:
            plan = await draft_plan_for_group(session, group_id)
            if plan is None:
                raise
    return await _apply_and_commit(
        session, plan, exam_date, lessons_per_week, lesson_minutes, past_paper_start_date
    )


async def _apply_and_commit(
    session: AsyncSession,
    plan: TeachingPlan,
    exam_date: date,
    lessons_per_week: int,
    lesson_minutes: int,
    past_paper_start_date: date | None,
) -> TeachingPlan:
    plan.exam_date = exam_date
    plan.lessons_per_week = lessons_per_week
    plan.lesson_minutes = lesson_minutes
    plan.past_paper_start_date = past_paper_start_date
    await session.commit()
    return await _reload(session, plan)


async def _reload(session: AsyncSession, plan: TeachingPlan) -> TeachingPlan:
    await session.refresh(plan, attribute_names=["breaks"])
    return plan


async def add_break(
    session: AsyncSession, *, plan: TeachingPlan, start_date: date, end_date: date, label: str
) -> PlanBreak:
    if end_date < start_date:
        raise PlanInputError("A break cannot end before it starts")
    # Serialise concurrent adds: lock the plan row (a no-op on SQLite) and read
    # its breaks inside the lock, so two requests cannot both pass the overlap
    # check against the same stale list.
    await session.scalar(
        select(TeachingPlan.id).where(TeachingPlan.id == plan.id).with_for_update()
    )
    await session.refresh(plan, attribute_names=["breaks"])
    for other in plan.breaks:
        if start_date <= other.end_date and other.start_date <= end_date:
            raise PlanInputError(
                f"This overlaps the break '{other.label}' "
                f"({other.start_date.isoformat()} to {other.end_date.isoformat()})"
            )
    plan_break = PlanBreak(plan_id=plan.id, start_date=start_date, end_date=end_date, label=label)
    session.add(plan_break)
    await session.commit()
    return plan_break


async def remove_break(session: AsyncSession, *, plan: TeachingPlan, break_id: int) -> bool:
    """Only a break of this (draft) plan; False when there is none."""
    plan_break = next((b for b in plan.breaks if b.id == break_id), None)
    if plan_break is None:
        return False
    await session.delete(plan_break)
    await session.commit()
    return True


# --- Reading the plan (task 6.4) ----------------------------------------------


async def _latest_draft_jobs(session: AsyncSession, plan_ids: set[int]) -> dict[int, JobStatus]:
    """Status of the newest `draft_plan` job per plan id, in one query.

    The payload is a JSON column with no equality operator on Postgres, so plan
    ids are matched in Python over a bounded, newest-first read of that one job
    type rather than in SQL.
    """
    if not plan_ids:
        return {}
    rows = (
        await session.execute(
            select(Job.payload, Job.status)
            .where(Job.type == PLAN_DRAFT_JOB)
            .order_by(Job.id.desc())
            .limit(200)
        )
    ).all()
    latest: dict[int, JobStatus] = {}
    for payload, status in rows:
        plan_id = payload.get("plan_id")
        if plan_id in plan_ids and plan_id not in latest:
            latest[plan_id] = status
    return latest


def _outcome(raw: dict | None, chapters: dict[int, Chapter]) -> DraftOutcomeOut | None:
    if not raw:
        return None
    failure = raw.get("failure") or {}
    entries = []
    for item in raw.get("chapters") or []:
        chapter = chapters.get(item["chapter_id"])
        entries.append(
            ChapterReasonOut(
                chapter_id=item["chapter_id"],
                chapter_code=chapter.code if chapter else None,
                chapter_title=chapter.title if chapter else None,
                weight=item["weight"],
                reason=item.get("reason"),
            )
        )
    return DraftOutcomeOut(
        status=raw.get("status", "failed"),
        drafted_at=raw.get("drafted_at"),
        weight_source=raw.get("weight_source"),
        degraded_reason=raw.get("degraded_reason"),
        guidance_used=bool(raw.get("guidance_used")),
        guidance_note=raw.get("guidance_note"),
        defaulted_chapters=raw.get("defaulted_chapters") or 0,
        chapters=entries,
        failure_code=failure.get("code"),
        failure_message=failure.get("message"),
    )


def _slot_out(slot: PlanSlot, chapter: Chapter) -> PlanSlotOut:
    return PlanSlotOut(
        id=slot.id,
        chapter_id=chapter.id,
        chapter_code=chapter.code,
        chapter_title=chapter.title,
        scheduled_date=slot.scheduled_date,
        sequence=slot.sequence,
        provenance=slot.provenance.value,
    )


async def plan_views(session: AsyncSession, plans: list[TeachingPlan]) -> dict[int, PlanInputsOut]:
    """Inputs, slots, drafting outcome and job state for each plan.

    Constant queries however many slots there are (`PERF-1`): one for every
    plan's slots joined to their chapter, one for the chapters the outcome
    names, one for the draft jobs. `plans` must have `breaks` loaded.
    """
    if not plans:
        return {}
    ids = {p.id for p in plans}
    slot_rows = (
        await session.execute(
            select(PlanSlot, Chapter)
            .join(Chapter, Chapter.id == PlanSlot.chapter_id)
            .where(PlanSlot.plan_id.in_(ids))
            .order_by(PlanSlot.scheduled_date, PlanSlot.sequence, PlanSlot.id)
        )
    ).all()
    chapter_ids = {c.id for _, c in slot_rows}
    for plan in plans:
        chapter_ids.update(i["chapter_id"] for i in (plan.draft_result or {}).get("chapters", []))
    chapters = {
        c.id: c for c in await session.scalars(select(Chapter).where(Chapter.id.in_(chapter_ids)))
    }
    jobs = await _latest_draft_jobs(session, ids)
    views: dict[int, PlanInputsOut] = {}
    for plan in plans:
        job = jobs.get(plan.id)
        views[plan.id] = PlanInputsOut(
            id=plan.id,
            exam_date=plan.exam_date,
            lessons_per_week=plan.lessons_per_week,
            lesson_minutes=plan.lesson_minutes,
            past_paper_start_date=plan.past_paper_start_date,
            breaks=[PlanBreakOut.model_validate(b) for b in plan.breaks],
            slots=[
                _slot_out(slot, chapter) for slot, chapter in slot_rows if slot.plan_id == plan.id
            ],
            outcome=_outcome(plan.draft_result, chapters),
            drafting=job in (JobStatus.pending, JobStatus.running),
            draft_job_failed=job is JobStatus.failed,
            accepted_at=plan.accepted_at,
        )
    return views


# --- Drafting, accepting, editing (task 6.4, AV-13) ----------------------------


async def request_draft(session: AsyncSession, group_id: int) -> None:
    """Queue the drafting job for the class's draft. A draft only exists once
    the inputs are saved (6.2), so none means there is nothing to draft from."""
    draft = await draft_plan_for_group(session, group_id)
    if draft is None:
        raise PlanStateError("Save the plan inputs before drafting a plan")
    # Already queued or running: a second job would redo the same work, and the
    # running one reads live state anyway.
    if (await _latest_draft_jobs(session, {draft.id})).get(draft.id) in (
        JobStatus.pending,
        JobStatus.running,
    ):
        return
    await enqueue_plan_draft(session, draft.id)
    await session.commit()


async def accept_plan(session: AsyncSession, *, group: Group, user: User) -> None:
    """Make the draft the live plan, replacing any previously accepted one.

    Nothing reads a draft (`accepted_plan_for_group` is the only reader), so this
    is the moment a plan starts to count. One transaction: lock both rows, drop
    the old accepted plan, promote the draft. UNIQUE(group_id, status) means the
    delete must reach the database before the status changes.
    """
    rows = (
        await session.scalars(
            select(TeachingPlan)
            .where(
                TeachingPlan.group_id == group.id,
                TeachingPlan.organization_id == group.organization_id,
            )
            .order_by(TeachingPlan.id)
            .with_for_update()
        )
    ).all()
    draft = next((p for p in rows if p.status is TeachingPlanStatus.draft), None)
    current = next((p for p in rows if p.status is TeachingPlanStatus.accepted), None)
    if draft is None:
        raise PlanStateError("There is no draft plan to accept")
    # Counted inside the lock: a count taken before it could be stale.
    slot_ids = (
        await session.scalars(select(PlanSlot.id).where(PlanSlot.plan_id == draft.id))
    ).all()
    if not slot_ids:
        raise PlanStateError("The draft has no lessons yet. Draft the plan first.")
    if (draft.draft_result or {}).get("status") != "drafted":
        raise PlanStateError(
            "The last drafting run did not produce a plan. Fix what it reports and draft again."
        )
    if current is not None:
        # Carrying taught or confirmed slots across a re-plan is task 6.6's job;
        # until then accepting a new draft replaces the live plan outright.
        # Children are deleted explicitly because SQLite (the test database) does
        # not enforce ON DELETE CASCADE, and an orphaned slot would be a real row.
        await session.execute(delete(PlanSlot).where(PlanSlot.plan_id == current.id))
        await session.execute(delete(PlanBreak).where(PlanBreak.plan_id == current.id))
        await session.execute(delete(TeachingPlan).where(TeachingPlan.id == current.id))
        session.expunge(current)
        await session.flush()
    draft.status = TeachingPlanStatus.accepted
    draft.accepted_at = utcnow()
    draft.accepted_by_id = user.id
    await session.commit()
    # Past-paper performance waits on the plan (5.7), and that gate only takes
    # effect on the next recompute, so every student in the class gets one.
    student_ids = (
        await session.scalars(
            select(GroupMember.student_id).where(GroupMember.group_id == group.id)
        )
    ).all()
    for student_id in student_ids:
        await enqueue_readiness_v2_debounced(session, student_id, group.subject_id)
    await session.commit()


async def edit_slot(
    session: AsyncSession,
    *,
    group: Group,
    slot_id: int,
    scheduled_date: date | None,
    chapter_id: int | None,
) -> PlanSlotOut:
    """Move a slot or change its chapter, on the draft or the accepted plan.

    No re-acceptance: the tutor owns the calendar (AV-13). The slot is looked up
    through its plan by class and organization, so another class's slot is a 404
    and not a 403 (`API-7`, `SEC-9`).
    """
    row = (
        await session.execute(
            select(PlanSlot, TeachingPlan)
            .join(TeachingPlan, TeachingPlan.id == PlanSlot.plan_id)
            .where(
                PlanSlot.id == slot_id,
                TeachingPlan.group_id == group.id,
                TeachingPlan.organization_id == group.organization_id,
            )
        )
    ).one_or_none()
    if row is None:
        raise PlanSlotNotFound(slot_id)
    slot, plan = row
    # Serialise edits to one plan so two renumbers cannot interleave (a no-op on SQLite).
    await session.scalar(
        select(TeachingPlan.id).where(TeachingPlan.id == plan.id).with_for_update()
    )
    await session.refresh(slot)

    new_chapter_id = chapter_id if chapter_id is not None else slot.chapter_id
    chapter = await session.scalar(
        select(Chapter).where(Chapter.id == new_chapter_id, Chapter.subject_id == group.subject_id)
    )
    if chapter is None:
        raise PlanInputError("That chapter is not part of this class's subject")
    new_date = scheduled_date if scheduled_date is not None else slot.scheduled_date
    if new_date >= plan.exam_date:
        raise PlanInputError("A lesson cannot be on or after the exam date")
    for brk in await session.scalars(select(PlanBreak).where(PlanBreak.plan_id == plan.id)):
        if brk.start_date <= new_date <= brk.end_date:
            raise PlanInputError(f"That date falls in the break '{brk.label}'")

    if new_date != slot.scheduled_date or new_chapter_id != slot.chapter_id:
        slot.scheduled_date = new_date
        slot.chapter_id = new_chapter_id
        # A confirmed or completed slot records a lesson that is happening or
        # happened (E15); moving it must not erase that. Only a slot that is
        # still the plan's intention becomes the tutor's own.
        if slot.provenance in (PlanSlotProvenance.generated, PlanSlotProvenance.manually_modified):
            slot.provenance = PlanSlotProvenance.manually_modified
        await session.flush()
        await renumber_slots(session, plan.id)
        await session.commit()
        await session.refresh(slot)
    return _slot_out(slot, chapter)
