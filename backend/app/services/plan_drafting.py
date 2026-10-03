"""Drafting a teaching plan's schedule (task 6.3, AV-14, E5).

Two deliberately separate steps. The AI advises, per chapter, how much teaching
time it deserves (`weigh_chapters`); the pure scheduler in `plan_scheduler`
owns the calendar. A model is never asked for a date.

Runs as a job (`BE-13`, `PERF-1`) whose payload is `{"plan_id": int}` and
nothing else (`BE-9`): the handler re-reads the plan, its class, the chapters,
the timetable and the breaks, so a retry or an orphan requeue sees current
state, not a stale snapshot.

Safe to re-run on the same payload (`BE-6`, `E15`): a run replaces the plan's
`generated` slots and touches no other provenance, so a second run yields the
same slots rather than a second copy. A tutor's `manually_modified` slot and any
`confirmed` or `completed` one is theirs (AV-77), and its date is treated as
taken so the generator never double-books it.
"""

import logging
import math
from dataclasses import dataclass, field

from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    AiFeature,
    Chapter,
    Group,
    Organization,
    PlanBreak,
    PlanSlot,
    PlanSlotProvenance,
    ScheduleSlot,
    Subject,
    TeachingPlan,
    TeachingPlanStatus,
)
from app.services import storage
from app.services.ai import (
    AIUnavailableError,
    file_block,
    record_usage,
    require_parsed,
    structured_complete,
)
from app.services.plan_scheduler import (
    ChapterWeight,
    DateRange,
    NotEnoughLessons,
    ScheduleInput,
    available_lesson_dates,
    effective_weekdays,
    schedule,
)
from app.services.prompts import CHAPTER_LIST_MARKERS
from app.services.timezones import now_in
from app.workers.jobs import enqueue

log = logging.getLogger("plan_drafting")

PLAN_DRAFT_JOB = "draft_plan"

# The advice is bounded so one confident answer cannot starve every other
# chapter, and the prompt says the same range.
MIN_WEIGHT = 0.5
MAX_WEIGHT = 3.0
DEFAULT_WEIGHT = 1.0

WEIGHTS_FROM_AI = "ai"
WEIGHTS_FROM_STORED = "stored_chapter_weights"


class ChapterAdvice(BaseModel):
    chapter_id: int = Field(description="The chapter_id exactly as printed in the CHAPTER LIST")
    weight: float = Field(description="Relative teaching time, 0.5 to 3.0; 1.0 is an ordinary one")
    reason: str = Field(description="One sentence a tutor can read and disagree with")


class PlanWeightingResult(BaseModel):
    chapters: list[ChapterAdvice]


@dataclass
class DraftResult:
    """What a run did. Returned to tests and logged, because the reasons have no
    column to live in (task 6.3 adds no migration) and `PROD-1` wants them kept
    somewhere a tutor-facing task can pick them up."""

    plan_id: int
    skipped: str | None = None  # why nothing was written, if so
    weight_source: str | None = None
    # Human-readable, set when the weights are not the AI's: a missing key.
    degraded_reason: str | None = None
    guidance_used: bool = False
    slots_written: int = 0
    defaulted_chapters: int = 0
    clamped_chapters: int = 0
    weights: dict[int, float] = field(default_factory=dict)
    reasons: dict[int, str] = field(default_factory=dict)


class PlanDraftError(ValueError):
    """A plan that cannot be drafted, with a message the tutor can act on."""


def _stored_weight(chapter: Chapter) -> float:
    w = chapter.weight
    return w if math.isfinite(w) and w > 0 else DEFAULT_WEIGHT


def _chapter_list_text(chapters: list[Chapter], *, has_guidance: bool) -> str:
    begin, end = CHAPTER_LIST_MARKERS
    lines = [begin]
    for chapter in chapters:
        topics = "; ".join(t.title for t in chapter.topics) or "(no topics listed)"
        lines.append(
            f"chapter_id={chapter.id} | {chapter.code} | {chapter.title} | topics: {topics}"
        )
    lines.append(end)
    guidance = (
        "The teaching guidance is attached as a document."
        if has_guidance
        else "No teaching guidance has been uploaded: weight from the chapter list alone."
    )
    return f"Weight these chapters for the teaching plan.\n{guidance}\n\n" + "\n".join(lines)


async def _guidance_block(subject: Subject) -> dict | None:
    if not subject.guidance_path or not subject.guidance_mime:
        return None
    try:
        data = await storage.read_file(subject.guidance_path)
    except Exception:  # noqa: BLE001 — an unreadable file degrades the advice, not the plan
        # The syllabus alone still supports a plan, and failing the job would
        # leave the tutor with nothing for a stored-file fault they cannot fix.
        # Logged at ERROR: an object a row points at and storage lost is an
        # operational fact.
        log.exception("teaching guidance for subject %s could not be read", subject.id)
        return None
    return file_block(data, subject.guidance_mime)


async def weigh_chapters(
    session: AsyncSession, *, group: Group, subject: Subject, chapters: list[Chapter]
) -> DraftResult:
    """Chapter weights from the AI, or from the stored `Chapter.weight` when AI is
    not configured. Fills `weights`, `reasons` and the bookkeeping on a result."""
    result = DraftResult(plan_id=0)
    by_id = {c.id: c for c in chapters}
    block = await _guidance_block(subject)
    content: list[dict] = []
    if block is not None:
        content.append(block)
    content.append(
        {"type": "text", "text": _chapter_list_text(chapters, has_guidance=block is not None)}
    )
    try:
        response = await structured_complete(
            surface="plan_weighting",
            content=content,
            output_format=PlanWeightingResult,
            max_tokens=4000,
        )
    except AIUnavailableError as exc:
        # `AI-20`, `INF-9`: a missing key degrades this surface and says so.
        result.weight_source = WEIGHTS_FROM_STORED
        result.degraded_reason = (
            f"{exc}. Chapter time was weighted from the weights stored on the chapters instead."
        )
        result.weights = {c.id: _stored_weight(c) for c in chapters}
        log.warning("plan weighting degraded for group %s: %s", group.id, result.degraded_reason)
        return result

    await record_usage(
        session,
        response,
        organization_id=group.organization_id,
        tutor_id=group.tutor_id,
        student_id=None,
        feature=AiFeature.plan_weighting,
    )
    advice = require_parsed(response)
    result.weight_source = WEIGHTS_FROM_AI
    result.guidance_used = block is not None
    for item in advice.chapters:
        # Unknown ids are ignored, and the first answer for an id wins, so a
        # model repeating itself or inventing a chapter cannot change the plan.
        if item.chapter_id not in by_id or item.chapter_id in result.weights:
            continue
        if not math.isfinite(item.weight):
            continue  # treated as missing below
        clamped = min(MAX_WEIGHT, max(MIN_WEIGHT, item.weight))
        if clamped != item.weight:
            result.clamped_chapters += 1
        result.weights[item.chapter_id] = clamped
        result.reasons[item.chapter_id] = item.reason.strip()
    for chapter in chapters:
        if chapter.id not in result.weights:
            result.weights[chapter.id] = DEFAULT_WEIGHT
            result.defaulted_chapters += 1
    return result


async def _load_draft(session: AsyncSession, plan_id: int) -> TeachingPlan | None:
    plan = await session.get(TeachingPlan, plan_id)
    if plan is None:
        log.info("plan %s no longer exists; nothing to draft", plan_id)
        return None
    if plan.status is not TeachingPlanStatus.draft:
        log.info("plan %s is %s, not a draft; leaving it alone", plan_id, plan.status.value)
        return None
    return plan


async def draft_plan_slots(session: AsyncSession, plan_id: int) -> DraftResult:
    """Generate the draft's `generated` slots. See the module docstring."""
    plan = await _load_draft(session, plan_id)
    if plan is None:
        return DraftResult(plan_id=plan_id, skipped="plan is gone or not a draft")
    group = await session.get(Group, plan.group_id)
    if group is None:
        log.info("plan %s: its class no longer exists; nothing to draft", plan_id)
        return DraftResult(plan_id=plan_id, skipped="class is gone")
    subject = await session.get(Subject, group.subject_id)
    organization = await session.get(Organization, group.organization_id)
    assert subject is not None and organization is not None
    chapters = list(
        (
            await session.scalars(
                select(Chapter)
                .where(Chapter.subject_id == subject.id)
                .options(selectinload(Chapter.topics))
                .order_by(Chapter.position, Chapter.id)
            )
        ).all()
    )
    if not chapters:
        raise PlanDraftError("This subject has no chapters yet, so there is nothing to plan.")

    weekdays = effective_weekdays(
        tuple(
            (
                await session.scalars(
                    select(ScheduleSlot.weekday).where(ScheduleSlot.group_id == group.id)
                )
            ).all()
        ),
        plan.lessons_per_week,
    )
    plan_breaks = (
        await session.scalars(select(PlanBreak).where(PlanBreak.plan_id == plan.id))
    ).all()
    breaks = tuple(DateRange(b.start_date, b.end_date) for b in plan_breaks)
    # Slots the generator does not own occupy their dates.
    kept_dates = set(
        (
            await session.scalars(
                select(PlanSlot.scheduled_date).where(
                    PlanSlot.plan_id == plan.id,
                    PlanSlot.provenance != PlanSlotProvenance.generated,
                )
            )
        ).all()
    )
    blocked = (*breaks, *(DateRange(d, d) for d in sorted(kept_dates)))
    # The tutor's own day, not the server's: at 01:00 in Cairo UTC still says
    # yesterday and the plan would open with a lesson that has already passed.
    start = now_in(organization.timezone).date()
    exam = plan.exam_date

    # Checked before the model is called, so a plan that cannot fit costs no AI
    # call and its usage is not lost to the rollback this raises into.
    lessons = len(available_lesson_dates(start, exam, weekdays, blocked))
    if lessons < len(chapters):
        raise NotEnoughLessons(lessons, len(chapters))

    result = await weigh_chapters(session, group=group, subject=subject, chapters=chapters)
    result.plan_id = plan.id

    # The model call may have been long. Take the row lock and re-check, so a
    # plan the tutor accepted meanwhile is not rewritten under them.
    locked = await session.scalar(
        select(TeachingPlan)
        .where(TeachingPlan.id == plan.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if locked is None or locked.status is not TeachingPlanStatus.draft:
        log.info("plan %s was accepted or removed while drafting; discarding the run", plan_id)
        return DraftResult(plan_id=plan_id, skipped="plan was accepted or removed during the run")

    lessons_out = schedule(
        ScheduleInput(
            chapters=tuple(ChapterWeight(c.id, result.weights[c.id]) for c in chapters),
            start_date=start,
            exam_date=exam,
            lesson_weekdays=weekdays,
            lessons_per_week=plan.lessons_per_week,
            breaks=blocked,
            past_paper_start_date=plan.past_paper_start_date,
        )
    )
    # Replace, never append: this filter is the whole of what keeps a re-run
    # idempotent and a tutor's edit safe.
    await session.execute(
        delete(PlanSlot)
        .where(PlanSlot.plan_id == plan.id, PlanSlot.provenance == PlanSlotProvenance.generated)
        .execution_options(synchronize_session=False)
    )
    session.add_all(
        PlanSlot(
            plan_id=plan.id,
            chapter_id=lesson.chapter_id,
            scheduled_date=lesson.scheduled_date,
            sequence=lesson.sequence,
            provenance=PlanSlotProvenance.generated,
        )
        for lesson in lessons_out
    )
    await session.flush()
    result.slots_written = len(lessons_out)
    log.info(
        "plan %s drafted: %s slots, weights from %s (%s defaulted, %s clamped), reasons=%s",
        plan.id,
        result.slots_written,
        result.weight_source,
        result.defaulted_chapters,
        result.clamped_chapters,
        result.reasons,
    )
    return result


async def draft_plan(session: AsyncSession, payload: dict) -> None:
    """Job handler for `draft_plan`. Failures raise, so the job row records them."""
    await draft_plan_slots(session, payload["plan_id"])


async def enqueue_plan_draft(session: AsyncSession, plan_id: int) -> None:
    """Queue a drafting run. For the plan-inputs endpoint (6.2) and re-plan (6.4)
    to call; the caller commits."""
    await enqueue(session, PLAN_DRAFT_JOB, {"plan_id": plan_id})
