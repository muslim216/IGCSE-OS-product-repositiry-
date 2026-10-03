"""Drafting a teaching plan's schedule (task 6.3, AV-14, E5).

Two deliberately separate steps. The AI advises, per chapter, how much teaching
time it deserves (`weigh_chapters`); the pure scheduler in `plan_scheduler`
owns the calendar. A model is never asked for a date.

Runs as a job (`BE-13`, `PERF-1`) whose payload is `{"plan_id": int}` and
nothing else (`BE-9`): the handler re-reads the plan, its class, the chapters,
the timetable and the breaks, so a retry or an orphan requeue sees current
state, not a stale snapshot.

Every run records what it did in `TeachingPlan.draft_result` (PROD-1, PROD-2):
the weights and reasons, whether the AI was used, degraded or unusable, and a
failure the tutor can act on. Failures no retry can fix (too few lessons, no
chapters) are written there and the job finishes normally; only transient
faults, such as a provider error, raise and are retried.

Safe to re-run (`BE-6`, `E15`): a run replaces the plan's `generated` slots and
touches no other provenance, so a second run yields the same slots rather than a
second copy. A tutor's `manually_modified` slot and any `confirmed` or
`completed` one is theirs (AV-77): its date is treated as taken, it counts
toward its chapter's share, and the plan is renumbered around it.
"""

import logging
import math
from dataclasses import dataclass, field

from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import async_session
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
from app.models.base import utcnow
from app.services import storage
from app.services.ai import (
    AIKeyMissingError,
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
# Reasons are kept for the tutor to read, not as an essay store.
STORED_REASON_CHARS = 300

WEIGHTS_FROM_AI = "ai"
WEIGHTS_FROM_STORED = "stored_chapter_weights"
# The AI answered but not one entry named a real chapter: nothing in it was
# used, and calling the result "ai" would pass an even split off as advice.
WEIGHTS_AI_UNUSABLE = "ai_unusable"

SKIPPED_ACCEPTED_MIDRUN = "plan was accepted or removed during the run"


class ChapterAdvice(BaseModel):
    chapter_id: int = Field(description="The chapter_id exactly as printed in the CHAPTER LIST")
    weight: float = Field(description="Relative teaching time, 0.5 to 3.0; 1.0 is an ordinary one")
    # No length limits on this schema: a limit turns a verbose answer into a parse
    # failure and a paid retry. Reasons are cut when stored instead.
    reason: str = Field(description="One sentence a tutor can read and disagree with")


class PlanWeightingResult(BaseModel):
    chapters: list[ChapterAdvice]


@dataclass
class DraftResult:
    """What a run did. `to_json` is the shape stored in `TeachingPlan.draft_result`."""

    plan_id: int
    status: str = "drafted"  # "drafted" | "failed" | "skipped"
    prompt_version: str | None = None
    weight_source: str | None = None
    # Human-readable, set whenever the weights are not plainly the AI's.
    degraded_reason: str | None = None
    guidance_used: bool = False
    guidance_note: str | None = None
    slots_written: int = 0
    defaulted_chapters: int = 0
    clamped_chapters: int = 0
    weights: dict[int, float] = field(default_factory=dict)
    reasons: dict[int, str] = field(default_factory=dict)
    failure: dict | None = None
    skipped: str | None = None  # why nothing was written, when status is "skipped"

    def to_json(self) -> dict:
        return {
            "status": self.status,
            "drafted_at": utcnow().isoformat(),
            "prompt_version": self.prompt_version,
            "weight_source": self.weight_source,
            "degraded_reason": self.degraded_reason,
            "guidance_used": self.guidance_used,
            "guidance_note": self.guidance_note,
            "defaulted_chapters": self.defaulted_chapters,
            "clamped_chapters": self.clamped_chapters,
            "chapters": [
                {
                    "chapter_id": cid,
                    "weight": weight,
                    "reason": (self.reasons.get(cid) or "")[:STORED_REASON_CHARS] or None,
                }
                for cid, weight in self.weights.items()
            ],
            "failure": self.failure,
        }


class PlanDraftError(ValueError):
    """A plan that cannot be drafted, with a message the tutor can act on."""

    def __init__(self, message: str, code: str = "no_chapters") -> None:
        super().__init__(message)
        self.code = code


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
        else "No teaching guidance is available: weight from the chapter list alone."
    )
    return f"Weight these chapters for the teaching plan.\n{guidance}\n\n" + "\n".join(lines)


async def _guidance_block(subject: Subject) -> tuple[dict | None, str | None]:
    """The guidance document as a content block, and a note when one was uploaded
    but could not be used. (None, None) means none was uploaded."""
    if not subject.guidance_path or not subject.guidance_mime:
        return None, None
    try:
        data = await storage.read_file(subject.guidance_path)
    except (OSError, storage.ObjectNotFoundError):  # OSError covers FileNotFoundError
        # The syllabus alone still supports a plan, and failing the job would
        # leave the tutor with nothing for a stored-file fault they cannot fix.
        # Narrow on purpose: anything else is a bug and should fail loudly.
        # Logged at ERROR: an object a row points at and storage lost is an
        # operational fact.
        log.exception("teaching guidance for subject %s could not be read", subject.id)
        return None, "The uploaded teaching guidance could not be read, so it was not used."
    return file_block(data, subject.guidance_mime), None


async def _meter(response, group: Group) -> None:
    """Record the call in its own short transaction. The tokens are spent whether
    or not the rest of the run commits, so the usage row must not ride on the
    handler's transaction, which rolls back if anything later raises (AI-17)."""
    async with async_session() as usage_session:
        await record_usage(
            usage_session,
            response,
            organization_id=group.organization_id,
            tutor_id=group.tutor_id,
            student_id=None,
            feature=AiFeature.plan_weighting,
        )
        await usage_session.commit()


async def weigh_chapters(*, group: Group, subject: Subject, chapters: list[Chapter]) -> DraftResult:
    """Chapter weights from the AI, or from the stored `Chapter.weight` when the
    key is missing or the answer is unusable. Fills `weights`, `reasons` and the
    bookkeeping on a result."""
    result = DraftResult(plan_id=0)
    by_id = {c.id: c for c in chapters}
    block, result.guidance_note = await _guidance_block(subject)
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
    except AIKeyMissingError as exc:
        # `AI-20`, `INF-9`: a missing key degrades this surface and says so. Only
        # the key: a missing SDK or a misrouted provider is a deployment fault.
        result.weight_source = WEIGHTS_FROM_STORED
        result.degraded_reason = (
            f"{exc}. Chapter time was weighted from the weights stored on the chapters instead."
        )
        result.weights = {c.id: _stored_weight(c) for c in chapters}
        log.warning("plan weighting degraded for group %s: %s", group.id, result.degraded_reason)
        return result

    await _meter(response, group)
    advice = require_parsed(response)
    result.prompt_version = response.prompt_version
    result.guidance_used = block is not None
    answered: dict[int, float] = {}
    for item in advice.chapters:
        # Bounded here, not in the schema (a schema limit turns a long answer into
        # a parse failure and a paid retry): once every real chapter has an answer
        # the rest cannot change the plan. Not a cap by position, so a real
        # chapter listed late is still read.
        if len(answered) == len(chapters):
            break
        # Unknown ids are ignored, and the first answer for an id wins, so a
        # model repeating itself or inventing a chapter cannot change the plan.
        if item.chapter_id not in by_id or item.chapter_id in answered:
            continue
        if not math.isfinite(item.weight):
            continue  # treated as missing below
        clamped = min(MAX_WEIGHT, max(MIN_WEIGHT, item.weight))
        if clamped != item.weight:
            result.clamped_chapters += 1
        answered[item.chapter_id] = clamped
        result.reasons[item.chapter_id] = item.reason.strip()
    if not answered:
        result.weight_source = WEIGHTS_AI_UNUSABLE
        result.degraded_reason = (
            "The AI's answer named none of this subject's chapters, so none of it was used. "
            "Chapter time was weighted from the weights stored on the chapters instead."
        )
        result.weights = {c.id: _stored_weight(c) for c in chapters}
        result.defaulted_chapters = len(chapters)
        result.reasons = {}
        result.guidance_used = False
        result.clamped_chapters = 0
        log.warning("plan weighting unusable for group %s", group.id)
        return result
    result.weight_source = WEIGHTS_FROM_AI
    for chapter in chapters:
        if chapter.id in answered:
            result.weights[chapter.id] = answered[chapter.id]
        else:
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


async def _weekdays(session: AsyncSession, group: Group, plan: TeachingPlan) -> tuple[int, ...]:
    """The lesson weekdays from the class timetable and the plan's lessons per week."""
    timetable = (
        await session.scalars(select(ScheduleSlot.weekday).where(ScheduleSlot.group_id == group.id))
    ).all()
    return effective_weekdays(tuple(timetable), plan.lessons_per_week)


async def _calendar(
    session: AsyncSession, plan: TeachingPlan
) -> tuple[tuple[DateRange, ...], dict[int, int]]:
    """Blocked dates (breaks plus dates the generator does not own) and, per
    chapter, how many non-generated slots the tutor already holds. Read fresh each
    time it matters, so it reflects any edit made while the model was thinking."""
    plan_breaks = (
        await session.scalars(select(PlanBreak).where(PlanBreak.plan_id == plan.id))
    ).all()
    kept = (
        await session.execute(
            select(PlanSlot.scheduled_date, PlanSlot.chapter_id).where(
                PlanSlot.plan_id == plan.id,
                PlanSlot.provenance != PlanSlotProvenance.generated,
            )
        )
    ).all()
    kept_counts: dict[int, int] = {}
    for _, chapter_id in kept:
        kept_counts[chapter_id] = kept_counts.get(chapter_id, 0) + 1
    blocked = (
        *(DateRange(b.start_date, b.end_date) for b in plan_breaks),
        *(DateRange(d, d) for d in sorted({row[0] for row in kept})),
    )
    return blocked, kept_counts


def _failed(
    plan_id: int, code: str, message: str, lessons: int | None = None, chapters: int | None = None
) -> DraftResult:
    return DraftResult(
        plan_id=plan_id,
        status="failed",
        failure={"code": code, "message": message, "lessons": lessons, "chapters": chapters},
    )


async def draft_plan_slots(session: AsyncSession, plan_id: int) -> DraftResult:
    """Generate the draft's `generated` slots and record the outcome on the plan.
    See the module docstring."""
    plan = await _load_draft(session, plan_id)
    if plan is None:
        return DraftResult(plan_id=plan_id, status="skipped", skipped="plan is gone or not a draft")
    try:
        result = await _draft(session, plan)
    except NotEnoughLessons as exc:
        result = _failed(plan.id, "not_enough_lessons", str(exc), exc.lessons, exc.chapters)
    except PlanDraftError as exc:
        result = _failed(plan.id, exc.code, str(exc))
    if result.skipped != SKIPPED_ACCEPTED_MIDRUN:
        # An accepted plan is the tutor's now; nothing of ours is written to it.
        plan.draft_result = result.to_json()
        await session.flush()
    if result.status == "failed":
        log.warning("plan %s could not be drafted: %s", plan.id, result.failure)
    return result


async def _draft(session: AsyncSession, plan: TeachingPlan) -> DraftResult:
    group = await session.get(Group, plan.group_id)
    if group is None:
        log.info("plan %s: its class no longer exists; nothing to draft", plan.id)
        return DraftResult(plan_id=plan.id, status="skipped", skipped="class is gone")
    subject = await session.get(Subject, group.subject_id)
    organization = await session.get(Organization, group.organization_id)
    if subject is None or organization is None:
        raise PlanDraftError(
            "This class's subject or organization could not be found.", code="missing_context"
        )
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

    weekdays = await _weekdays(session, group, plan)
    # The tutor's own day, not the server's: at 01:00 in Cairo UTC still says
    # yesterday and the plan would open with a lesson that has already passed.
    start = now_in(organization.timezone).date()
    exam = plan.exam_date

    # Checked before the model is called, so a plan that cannot fit costs no AI
    # call. Chapters the tutor already holds a slot for need no new lesson.
    blocked, kept_counts = await _calendar(session, plan)
    free = len(available_lesson_dates(start, exam, weekdays, blocked))
    needing = sum(1 for c in chapters if kept_counts.get(c.id, 0) == 0)
    if free < needing:
        raise NotEnoughLessons(free, needing)

    result = await weigh_chapters(group=group, subject=subject, chapters=chapters)
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
        log.info("plan %s was accepted or removed while drafting; discarding the run", plan.id)
        return DraftResult(plan_id=plan.id, status="skipped", skipped=SKIPPED_ACCEPTED_MIDRUN)
    # Re-read under the lock: the timetable, breaks and the tutor's own slots can
    # change while the model is thinking, and the schedule must see the current
    # ones. `locked` is the same identity as `plan`, refreshed, so its exam date
    # and lessons per week are current too.
    weekdays = await _weekdays(session, group, plan)
    exam = plan.exam_date
    blocked, kept_counts = await _calendar(session, plan)

    lessons_out = schedule(
        ScheduleInput(
            chapters=tuple(
                ChapterWeight(c.id, result.weights[c.id], kept_counts.get(c.id, 0))
                for c in chapters
            ),
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
    await _renumber(session, plan.id)
    result.slots_written = len(lessons_out)
    log.info(
        "plan %s drafted: %s slots, weights from %s (%s defaulted, %s clamped)",
        plan.id,
        result.slots_written,
        result.weight_source,
        result.defaulted_chapters,
        result.clamped_chapters,
    )
    return result


async def _renumber(session: AsyncSession, plan_id: int) -> None:
    """Number every slot of the plan 1..n by (date, id), the tutor's own included.
    Generated and kept slots are scheduled independently, so their sequences would
    otherwise collide; `sequence` is the plan's order and must be one run."""
    rows = (
        await session.scalars(
            select(PlanSlot)
            .where(PlanSlot.plan_id == plan_id)
            .order_by(PlanSlot.scheduled_date, PlanSlot.id)
            .execution_options(populate_existing=True)
        )
    ).all()
    for number, row in enumerate(rows, start=1):
        if row.sequence != number:
            row.sequence = number
    await session.flush()


async def draft_plan(session: AsyncSession, payload: dict) -> None:
    """Job handler for `draft_plan`. Only faults a retry could fix raise."""
    await draft_plan_slots(session, payload["plan_id"])


async def enqueue_plan_draft(session: AsyncSession, plan_id: int) -> None:
    """Queue a drafting run. For the plan-inputs endpoint (6.2) and re-plan (6.4)
    to call; the caller commits."""
    await enqueue(session, PLAN_DRAFT_JOB, {"plan_id": plan_id})
