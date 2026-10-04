"""Teaching-plan inputs (task 6.2, AV-15): exam date, pace, past-paper start, breaks.

Everything here mirrors the 6.1 CHECK constraints as explicit validation so a bad
value is a 422 from the API rather than an IntegrityError 500.
"""

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, time

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
    Lesson,
    LessonOrigin,
    PlanBreak,
    PlanSlot,
    PlanSlotProvenance,
    ScheduleSlot,
    TeachingPlan,
    TeachingPlanStatus,
    Topic,
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
    ReflowOut,
)
from app.services.plan_drafting import PLAN_DRAFT_JOB, enqueue_plan_draft, renumber_slots
from app.services.plan_start_times import timetable_start_times
from app.services.plan_timing import split_topics, timetable_default
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


#: Key in `TeachingPlan.draft_result`: ids of cancelled slots whose content was
#: not rescheduled (task 7.4). A key rather than a column because 7.4 adds no
#: migration. Written by `plan_cancel` and `plan_lessons`; read by `plan_progress`.
UNRESCHEDULED_KEY = "unrescheduled_cancellations"

#: A slot in either state is already spoken for: `confirmed` is a lesson in hand,
#: `completed` one that happened (E15). Neither is "next".
STARTED_PROVENANCE = (PlanSlotProvenance.confirmed, PlanSlotProvenance.completed)


def note_unrescheduled(plan: TeachingPlan, slot_id: int) -> None:
    """Record that this cancelled slot's content was not rescheduled, so "behind"
    reports it. Reassigned, not mutated, so the JSON column registers the change."""
    held = (plan.draft_result or {}).get(UNRESCHEDULED_KEY) or []
    plan.draft_result = {**(plan.draft_result or {}), UNRESCHEDULED_KEY: sorted({*held, slot_id})}


@dataclass(frozen=True)
class NextLesson:
    slot: PlanSlot
    chapter: Chapter
    topics: list[Topic]


def effective_start_time(
    slot_start: time | None, by_weekday: dict[int, time], day: date
) -> time | None:
    """The slot's own start time, else the timetable's for its weekday, else None.
    The one read-time fallback for slots that predate the column (`DB-9`): NULL is
    unknown, never midnight."""
    return slot_start if slot_start is not None else timetable_default(by_weekday, day)


async def chapter_topics(session: AsyncSession, chapter: Chapter) -> list[Topic]:
    """The chapter's topics in teaching order, inside its own subject (`SEC-8`)."""
    return list(
        await session.scalars(
            select(Topic)
            .where(Topic.chapter_id == chapter.id, Topic.subject_id == chapter.subject_id)
            .order_by(Topic.id)
        )
    )


async def topic_share(
    session: AsyncSession, *, plan_id: int, slot: PlanSlot, chapter: Chapter
) -> list[Topic]:
    """The slot's share of its chapter's topics (task 7.4, AV-119): the chapter's
    topics split in order across the chapter's non-cancelled planned lessons,
    ordered by date then sequence. A cancelled slot is not a lesson, so it takes
    no share and its replacement takes its place in the order."""
    ordered = list(
        await session.scalars(
            select(PlanSlot.id)
            .where(
                PlanSlot.plan_id == plan_id,
                PlanSlot.chapter_id == chapter.id,
                PlanSlot.cancelled_at.is_(None),
            )
            .order_by(PlanSlot.scheduled_date, PlanSlot.sequence, PlanSlot.id)
        )
    )
    if slot.id not in ordered:
        return []
    return split_topics(
        await chapter_topics(session, chapter), ordered.index(slot.id), len(ordered)
    )


async def next_unstarted_slot(
    session: AsyncSession, group_id: int, slot_id: int | None = None
) -> NextLesson | None:
    """The earliest slot of the *accepted* plan that no lesson has started, with
    its share of the chapter's topics (task 6.5, AV-17; the share is 7.4, AV-119).
    None when there is no accepted plan or nothing is left.

    Goes through `accepted_plan_for_group`, so a draft is never suggested from.
    "Unstarted" is `lesson_id IS NULL` and provenance not confirmed/completed;
    both are checked because 6.8 may mark a slot taught without a lesson row. A
    cancelled slot is not a lesson to suggest. Topics are the same share the
    auto-record writes, so the suggestion and the record agree.

    `slot_id` asks about one specific slot instead (the reminder's "Review"
    opens the form for the lesson about to start, which is not always the
    earliest unstarted one). It must still be an unstarted, uncancelled slot of
    this class's accepted plan, or the answer is None.
    """
    plan = await accepted_plan_for_group(session, group_id)
    if plan is None:
        return None
    query = select(PlanSlot).where(
        PlanSlot.plan_id == plan.id,
        PlanSlot.lesson_id.is_(None),
        PlanSlot.provenance.not_in(STARTED_PROVENANCE),
        PlanSlot.cancelled_at.is_(None),
    )
    if slot_id is not None:
        query = query.where(PlanSlot.id == slot_id)
    slot = await session.scalar(
        query.order_by(PlanSlot.scheduled_date, PlanSlot.sequence, PlanSlot.id).limit(1)
    )
    if slot is None:
        return None
    chapter = await session.get(Chapter, slot.chapter_id)
    if chapter is None:  # RESTRICT on the FK makes this unreachable; never invent one.
        return None
    topics = await topic_share(session, plan_id=plan.id, slot=slot, chapter=chapter)
    return NextLesson(slot=slot, chapter=chapter, topics=topics)


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


async def _relock_draft(session: AsyncSession, plan: TeachingPlan) -> TeachingPlan | None:
    """Lock the plan row and reload it; None when it is no longer a draft
    (promoted by an accept, or gone). The lock is a no-op on SQLite."""
    fresh = await session.scalar(
        select(TeachingPlan)
        .where(TeachingPlan.id == plan.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if fresh is None or fresh.status is not TeachingPlanStatus.draft:
        return None
    return fresh


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
    if plan is not None:
        # The read above can be stale by the time we write: an accept that
        # promoted this very row in between would otherwise have its inputs
        # overwritten here. Lock and re-read; a plan that is no longer a draft
        # is "no draft", so a new one is made beside the accepted plan.
        plan = await _relock_draft(session, plan)
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
            plan = await _relock_draft(session, plan) if plan is not None else None
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
    changed = (
        plan.exam_date != exam_date
        or plan.lessons_per_week != lessons_per_week
        or plan.lesson_minutes != lesson_minutes
        or plan.past_paper_start_date != past_paper_start_date
    )
    plan.exam_date = exam_date
    plan.lessons_per_week = lessons_per_week
    plan.lesson_minutes = lesson_minutes
    plan.past_paper_start_date = past_paper_start_date
    if changed:
        mark_draft_stale(plan)
    await session.commit()
    return await _reload(session, plan)


def mark_draft_stale(plan: TeachingPlan) -> None:
    """The slots were built for inputs that no longer hold, so accepting them
    would promote a plan nobody asked for. A redraft overwrites `draft_result`.
    Reassigned, not mutated, so the JSON column registers the change. A plan
    that was never drafted has nothing to go stale."""
    if plan.draft_result:
        plan.draft_result = {**plan.draft_result, "status": "stale"}


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
    locked = await _relock_draft(session, plan)
    if locked is None:
        raise PlanStateError("Save the plan inputs before adding breaks")
    plan = locked
    await session.refresh(plan, attribute_names=["breaks"])
    for other in plan.breaks:
        if start_date <= other.end_date and other.start_date <= end_date:
            raise PlanInputError(
                f"This overlaps the break '{other.label}' "
                f"({other.start_date.isoformat()} to {other.end_date.isoformat()})"
            )
    plan_break = PlanBreak(plan_id=plan.id, start_date=start_date, end_date=end_date, label=label)
    session.add(plan_break)
    mark_draft_stale(plan)
    await session.commit()
    return plan_break


async def remove_break(session: AsyncSession, *, plan: TeachingPlan, break_id: int) -> bool:
    """Only a break of this (draft) plan; False when there is none."""
    locked = await _relock_draft(session, plan)
    if locked is None:
        return False
    plan = locked
    await session.refresh(plan, attribute_names=["breaks"])
    plan_break = next((b for b in plan.breaks if b.id == break_id), None)
    if plan_break is None:
        return False
    await session.delete(plan_break)
    mark_draft_stale(plan)
    await session.commit()
    return True


# --- Reading the plan (task 6.4) ----------------------------------------------


async def _latest_draft_jobs(session: AsyncSession, plan_ids: set[int]) -> dict[int, JobStatus]:
    """Status of the newest `draft_plan` job per plan id, in one query.

    Filtered in SQL on the plan id inside the payload, so a busy queue of other
    classes' drafts cannot push this plan's job out of view. Every status is
    read, not only the live ones: an older failed job must not be reported as
    the latest once a newer one has finished.
    """
    if not plan_ids:
        return {}
    rows = (
        await session.execute(
            select(Job.payload, Job.status)
            .where(
                Job.type == PLAN_DRAFT_JOB,
                Job.payload["plan_id"].as_integer().in_(plan_ids),
            )
            .order_by(Job.id.desc())
            .limit(20 * len(plan_ids))
        )
    ).all()
    latest: dict[int, JobStatus] = {}
    for payload, status in rows:
        plan_id = payload.get("plan_id")
        if plan_id in plan_ids and plan_id not in latest:
            latest[plan_id] = status
    return latest


def _reflow(raw: dict | None) -> ReflowOut | None:
    """What the last syllabus-change reflow did (task 6.8), for the tutor (PROD-1)."""
    if not raw:
        return None
    failure = raw.get("failure") or {}
    return ReflowOut(
        status=raw.get("status", "failed"),
        at=raw.get("at"),
        reason=raw.get("reason"),
        failure_message=failure.get("message"),
        last_success_at=raw.get("last_success_at"),
    )


def _outcome(raw: dict | None, chapters: dict[int, Chapter]) -> DraftOutcomeOut | None:
    # `draft_result` also carries plan-level notes written after drafting (task
    # 7.4's unrescheduled cancellations); a dict with no drafting status is not
    # a drafting outcome and must not read as a failed one.
    if not raw or "status" not in raw:
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
        reflow=_reflow(raw.get("reflow")),
    )


def _slot_out(
    slot: PlanSlot,
    chapter: Chapter,
    by_weekday: dict[int, time],
    lesson_origin: LessonOrigin | None = None,
) -> PlanSlotOut:
    return PlanSlotOut(
        id=slot.id,
        chapter_id=chapter.id,
        chapter_code=chapter.code,
        chapter_title=chapter.title,
        scheduled_date=slot.scheduled_date,
        sequence=slot.sequence,
        provenance=slot.provenance.value,
        start_time=effective_start_time(slot.start_time, by_weekday, slot.scheduled_date),
        cancelled=slot.cancelled_at is not None,
        lesson_id=slot.lesson_id,
        lesson_origin=lesson_origin.value if lesson_origin else None,
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
    timetable = await timetable_start_times(session, [p.group_id for p in plans])
    lesson_ids = {slot.lesson_id for slot, _ in slot_rows if slot.lesson_id is not None}
    origins: dict[int, LessonOrigin] = {}
    if lesson_ids:
        origins = dict(
            (
                await session.execute(
                    select(Lesson.id, Lesson.origin).where(Lesson.id.in_(lesson_ids))
                )
            ).all()  # type: ignore[arg-type]
        )
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
                _slot_out(
                    slot,
                    chapter,
                    timetable.get(plan.group_id, {}),
                    origins.get(slot.lesson_id) if slot.lesson_id is not None else None,
                )
                for slot, chapter in slot_rows
                if slot.plan_id == plan.id
            ],
            outcome=_outcome(plan.draft_result, chapters),
            drafting=job in (JobStatus.pending, JobStatus.running),
            draft_job_failed=job is JobStatus.failed,
            accepted_at=plan.accepted_at,
        )
    return views


# --- Drafting, accepting, editing (task 6.4, AV-13) ----------------------------


async def lock_group_plans(session: AsyncSession, group_id: int) -> list[TeachingPlan]:
    """Every plan row of the class, locked in id order (the order `accept_plan`
    takes them, so the two cannot deadlock). A no-op lock on SQLite. The caller
    has already authorised the class, so the class id alone scopes the rows."""
    return list(
        (
            await session.scalars(
                select(TeachingPlan)
                .where(TeachingPlan.group_id == group_id)
                .order_by(TeachingPlan.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).all()
    )


async def request_draft(session: AsyncSession, group_id: int) -> None:
    """Queue the drafting job for the class's draft. A draft only exists once
    the inputs are saved (6.2), so none means there is nothing to draft from."""
    # The same lock `replan` takes, and the job is checked under it: without
    # that, a draft click and a re-plan click can each see "no job" and both queue one.
    rows = await lock_group_plans(session, group_id)
    draft = next((p for p in rows if p.status is TeachingPlanStatus.draft), None)
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
    # A job still running would write slots into a plan that is already live.
    latest_job = (await _latest_draft_jobs(session, {draft.id})).get(draft.id)
    if latest_job in (JobStatus.pending, JobStatus.running):
        raise PlanStateError("The plan is still being drafted. Wait for it to finish.")
    # A redraft that died leaves the previous run's slots and a "drafted" result
    # in place, so that result describes a plan the tutor asked to replace.
    if latest_job is JobStatus.failed:
        raise PlanStateError("The last drafting attempt failed. Draft again before accepting.")
    result_status = (draft.draft_result or {}).get("status")
    if result_status == "stale":
        raise PlanStateError(
            "The plan inputs or breaks changed since this draft was made. Draft again first."
        )
    if result_status != "drafted":
        raise PlanStateError(
            "The last drafting run did not produce a plan. Fix what it reports and draft again."
        )
    if current is not None:
        # Recorded lessons keep their slot (task 6.6, E15): a lesson is linked to
        # a slot of the *accepted* plan, and that plan is about to be deleted.
        linked_rows = (
            await session.execute(
                select(
                    PlanSlot.lesson_id,
                    PlanSlot.chapter_id,
                    PlanSlot.scheduled_date,
                    PlanSlot.provenance,
                )
                .where(PlanSlot.plan_id == current.id, PlanSlot.lesson_id.is_not(None))
                # Locked so a lesson delete (which takes the plan lock first, see
                # `release_slot_for_lesson`) cannot clear a link between this read
                # and the carry below.
                .with_for_update()
            )
        ).all()
        linked = [(r[0], r[1], r[2], r[3]) for r in linked_rows if r[0] is not None]
        # Children are deleted explicitly because SQLite (the test database) does
        # not enforce ON DELETE CASCADE, and an orphaned slot would be a real row.
        # Deleting the old slots before linking is what frees `uq_plan_slots_lesson_id`.
        await session.execute(delete(PlanSlot).where(PlanSlot.plan_id == current.id))
        await session.execute(delete(PlanBreak).where(PlanBreak.plan_id == current.id))
        await session.execute(delete(TeachingPlan).where(TeachingPlan.id == current.id))
        session.expunge(current)
        await session.flush()
        await _carry_lesson_links(session, draft, linked)
    draft.status = TeachingPlanStatus.accepted
    draft.accepted_at = utcnow()
    draft.accepted_by_id = user.id
    # Past-paper performance waits on the plan (5.7), and that gate only takes
    # effect on the next recompute, so every student in the class gets one.
    # Enqueued before the commit (the helper does not commit), so the accept and
    # its recomputes land together or not at all.
    student_ids = (
        await session.scalars(
            select(GroupMember.student_id).where(GroupMember.group_id == group.id)
        )
    ).all()
    for student_id in student_ids:
        await enqueue_readiness_v2_debounced(session, student_id, group.subject_id)
    await session.commit()


async def _carry_lesson_links(
    session: AsyncSession,
    draft: TeachingPlan,
    linked: Sequence[tuple[int, int, date, PlanSlotProvenance]],
) -> None:
    """Move each recorded lesson's link onto the draft (task 6.6).

    A re-plan copies the taught slots into the draft without their `lesson_id`;
    each old link goes to the copy matching on chapter + date + provenance. A
    lesson with no match (a plain redraft never copied it, or the tutor moved the
    copy) is NOT dropped: it becomes a new slot in the draft with the lesson's
    old chapter, date and provenance. Losing the link would put a taught lesson
    back in the plan as an untaught one and 6.5 would suggest it again.
    """
    # A lesson deleted since the links were read has nothing to link to; carrying
    # its id would be a foreign-key failure that aborts the whole accept.
    alive = set(
        await session.scalars(select(Lesson.id).where(Lesson.id.in_([r[0] for r in linked])))
    )
    linked = [row for row in linked if row[0] in alive]
    lesson_starts: dict[int, time | None] = {
        lid: start
        for lid, start in (
            await session.execute(select(Lesson.id, Lesson.start_time).where(Lesson.id.in_(alive)))
        ).tuples()
    }
    free = list(
        (
            await session.scalars(
                select(PlanSlot)
                .where(PlanSlot.plan_id == draft.id, PlanSlot.lesson_id.is_(None))
                .order_by(PlanSlot.sequence, PlanSlot.id)
            )
        ).all()
    )
    assigned: dict[int, PlanSlot] = {}
    # Pass 1: every exact (chapter, date, provenance) match, for all links first.
    # Doing the nearest-copy fallback in the same loop let one lesson take
    # another's exact-date copy before that lesson was processed, swapping links
    # between two same-chapter lessons.
    for lesson_id, chapter_id, scheduled_date, provenance in linked:
        exact = next(
            (
                s
                for s in free
                if s.chapter_id == chapter_id
                and s.scheduled_date == scheduled_date
                and s.provenance is provenance
            ),
            None,
        )
        if exact is not None:
            free.remove(exact)
            assigned[lesson_id] = exact
    # Pass 2: only the leftover links, over only the leftover copies. The tutor may
    # have moved a copy in the draft; its chapter and provenance still say which
    # lesson it was, so take the nearest such copy rather than leave an edited
    # "taught" slot with no lesson beside a duplicate that has one.
    for lesson_id, chapter_id, scheduled_date, provenance in linked:
        if lesson_id in assigned:
            continue
        moved = [s for s in free if s.chapter_id == chapter_id and s.provenance is provenance]
        near = min(moved, key=lambda s: abs((s.scheduled_date - scheduled_date).days), default=None)
        if near is not None:
            free.remove(near)
            assigned[lesson_id] = near
            continue
        fresh = PlanSlot(
            plan_id=draft.id,
            chapter_id=chapter_id,
            scheduled_date=scheduled_date,
            sequence=0,
            provenance=provenance,
            # The lesson's own start time: the slot's was on a plan being replaced.
            start_time=lesson_starts.get(lesson_id),
        )
        session.add(fresh)
        assigned[lesson_id] = fresh
    for lesson_id, slot in assigned.items():
        slot.lesson_id = lesson_id
    await session.flush()
    await renumber_slots(session, draft.id)


async def edit_slot(
    session: AsyncSession,
    *,
    group: Group,
    slot_id: int,
    scheduled_date: date | None,
    chapter_id: int | None,
    start_time: time | None = None,
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
    # Re-read under the lock: a redraft that ran in between may have replaced
    # the slot, which is then a 404 rather than a failed refresh.
    reread = await session.scalar(
        select(PlanSlot)
        .where(PlanSlot.id == slot_id, PlanSlot.plan_id == plan.id)
        # Plan lock is already held, so plan-then-slot order holds. The slot lock
        # stops a concurrent lesson confirm landing between this read and the write.
        .with_for_update(of=PlanSlot)
        .execution_options(populate_existing=True)
    )
    if reread is None:
        raise PlanSlotNotFound(slot_id)
    slot = reread
    if slot.cancelled_at is not None:
        raise PlanStateError("That lesson was cancelled; it cannot be edited")

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

    by_weekday = (await timetable_start_times(session, [group.id])).get(group.id, {})
    date_moved = new_date != slot.scheduled_date
    start_changed = start_time is not None and start_time != slot.start_time
    if date_moved or new_chapter_id != slot.chapter_id or start_changed:
        slot.scheduled_date = new_date
        slot.chapter_id = new_chapter_id
        if start_time is not None:
            slot.start_time = start_time
        elif date_moved:
            # A new weekday has a different timetable time; keeping the old time
            # would put the lesson at an hour that class never meets. NULL when
            # the timetable has none for that day (never midnight, `DB-9`).
            slot.start_time = timetable_default(by_weekday, new_date)
        # A confirmed or completed slot records a lesson that is happening or
        # happened (E15); moving it must not erase that. Only a slot that is
        # still the plan's intention becomes the tutor's own.
        if slot.lesson_id is None and slot.provenance in (
            PlanSlotProvenance.generated,
            PlanSlotProvenance.manually_modified,
        ):
            slot.provenance = PlanSlotProvenance.manually_modified
        await session.flush()
        await renumber_slots(session, plan.id)
        await session.commit()
        await session.refresh(slot)
    origin = (
        await session.scalar(select(Lesson.origin).where(Lesson.id == slot.lesson_id))
        if slot.lesson_id is not None
        else None
    )
    return _slot_out(slot, chapter, by_weekday, origin)
