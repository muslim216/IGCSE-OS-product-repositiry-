"""Automatic plan reflow when a subject's chapters change (task 6.8, AV-68, AV-77, E13).

Adding, splitting, reordering or removing a chapter re-lays the plan's future
lessons with no acceptance step. Runs as a job (`BE-13`, `PERF-1`) whose payload
is `{"plan_id": int}` and nothing else (`BE-9`); the handler re-reads current
state, so a retry or an orphan requeue is safe (`BE-6`).

Mechanical on purpose: no AI call. The chapter weights the tutor already saw
come from the plan's last drafting run (`draft_result.chapters`), and a chapter
that run never weighed takes its stored `Chapter.weight`. Asking a model again
would silently re-weigh chapters the tutor had accepted, and cost a call for a
change that only moved the order.

Only `generated` slots dated after today move (AV-77). A `manually_modified`,
`confirmed` or `completed` slot is the tutor's; a slot dated today or earlier is
the lesson being given or already given. Those stay, their dates are blocked and
they count toward their chapter's share, exactly as in the 6.3 draft.

Every outcome of a plan that has a `draft_result` is written to
`draft_result["reflow"]` (`PROD-1`): reflowed, failed or skipped. A plan that is
gone, or has no `draft_result` to hold a record, is only logged. Deterministic
failures (too few lessons, no chapters) end the job `done`, since a retry cannot
fix them, so they live only in `draft_result` and the log, not in the jobs table.
"""

import logging
from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Chapter,
    Group,
    Organization,
    PlanSlot,
    PlanSlotProvenance,
    Subject,
    TeachingPlan,
)
from app.models.base import utcnow
from app.services.plan_drafting import _calendar, _stored_weight, _weekdays, renumber_slots
from app.services.plan_scheduler import (
    ChapterWeight,
    NotEnoughLessons,
    ScheduleInput,
    schedule,
)
from app.services.timezones import now_in
from app.workers.jobs import enqueue

log = logging.getLogger("plan_reflow")

PLAN_REFLOW_JOB = "reflow_plan"


def _record(plan: TeachingPlan, outcome: dict) -> None:
    # Reassigned, not mutated: a JSON column does not see an in-place change.
    previous = (plan.draft_result or {}).get("reflow") or {}
    if outcome["status"] == "failed":
        # A failure must not erase when the plan last reflowed successfully.
        outcome["last_success_at"] = (
            previous.get("at")
            if previous.get("status") == "reflowed"
            else previous.get("last_success_at")
        )
    plan.draft_result = {**(plan.draft_result or {}), "reflow": outcome}


def _skip(plan: TeachingPlan | None, plan_id: int, reason: str) -> None:
    status = plan.draft_result.get("status") if plan and plan.draft_result else None
    log.warning("plan %s not reflowed (draft status %s): %s", plan_id, status, reason)
    if plan is not None and plan.draft_result is not None:
        _record(plan, {"at": utcnow().isoformat(), "status": "skipped", "reason": reason})


async def reflow_plan_slots(session: AsyncSession, plan_id: int) -> dict | None:
    """Reflow one plan. Returns the recorded outcome, or None when nothing applies."""
    # Locked first and refreshed, so a tutor's concurrent edit or acceptance is
    # seen and the slot rewrite cannot interleave with theirs.
    plan = await session.scalar(
        select(TeachingPlan)
        .where(TeachingPlan.id == plan_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if plan is None:
        _skip(None, plan_id, "the plan no longer exists")
        return None
    # A plan never drafted (or whose draft failed) has no schedule to adjust;
    # writing slots here would bypass the weighing the draft job exists to do.
    if (plan.draft_result or {}).get("status") != "drafted":
        _skip(plan, plan_id, "the plan has no current drafted schedule to adjust")
        return None
    group = await session.get(Group, plan.group_id)
    if group is None:
        _skip(plan, plan_id, "the plan's class no longer exists")
        return None
    subject = await session.get(Subject, group.subject_id)
    organization = await session.get(Organization, group.organization_id)
    if subject is None or organization is None:
        _skip(plan, plan_id, "the class's subject or organization could not be found")
        return None

    # CODE-12: this is intentionally NOT the 6.6 behaviour. A behind-schedule
    # re-plan recalculates and then WAITS for the tutor to accept (E15). A syllabus
    # edit reflows straight into the plan, accepted or draft, with no acceptance
    # step (AV-68, E13): the tutor changed the chapters themselves, so there is
    # nothing to confirm, and the slots they own are untouched. Not a bug.
    chapters = list(
        (
            await session.scalars(
                select(Chapter)
                .where(Chapter.subject_id == subject.id)
                .order_by(Chapter.position, Chapter.id)
            )
        ).all()
    )
    today = now_in(organization.timezone).date()
    at = utcnow().isoformat()

    def fail(code: str, message: str, **extra: int | None) -> dict:
        outcome = {
            "at": at,
            "status": "failed",
            "failure": {"code": code, "message": message, **extra},
        }
        _record(plan, outcome)
        return outcome

    if not chapters:
        outcome = fail("no_chapters", "This subject has no chapters, so the plan was not changed.")
        await session.flush()
        log.warning("plan %s could not be reflowed: subject has no chapters", plan.id)
        return outcome

    stored = {
        entry["chapter_id"]: entry["weight"]
        for entry in (plan.draft_result or {}).get("chapters", [])
        if isinstance(entry, dict) and isinstance(entry.get("weight"), int | float)
    }
    weights = {c.id: stored.get(c.id, _stored_weight(c)) for c in chapters}

    weekdays = await _weekdays(session, group, plan)
    blocked, kept_counts = await _calendar(session, plan, generated_through=today)
    try:
        lessons_out = schedule(
            ScheduleInput(
                chapters=tuple(
                    ChapterWeight(c.id, weights[c.id], kept_counts.get(c.id, 0)) for c in chapters
                ),
                # Tomorrow in the tutor's own day; today's lesson is not moved.
                start_date=today + timedelta(days=1),
                exam_date=plan.exam_date,
                lesson_weekdays=weekdays,
                lessons_per_week=plan.lessons_per_week,
                breaks=blocked,
                past_paper_start_date=plan.past_paper_start_date,
            )
        )
    except NotEnoughLessons as exc:
        # Nothing was deleted yet, so the plan is exactly as the tutor left it.
        outcome = fail("not_enough_lessons", str(exc), lessons=exc.lessons, chapters=exc.chapters)
        await session.flush()
        log.warning("plan %s could not be reflowed: %s", plan.id, outcome["failure"])
        return outcome

    # These two filters are what keep a tutor's slot and a past lesson safe, and a
    # re-run idempotent: generated only, and strictly after today.
    await session.execute(
        delete(PlanSlot)
        .where(
            PlanSlot.plan_id == plan.id,
            PlanSlot.provenance == PlanSlotProvenance.generated,
            PlanSlot.scheduled_date > today,
        )
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
    await renumber_slots(session, plan.id)
    outcome = {"at": at, "status": "reflowed", "slots_written": len(lessons_out), "failure": None}
    _record(plan, outcome)
    await session.flush()
    log.info("plan %s reflowed: %s slots", plan.id, len(lessons_out))
    return outcome


async def reflow_plan(session: AsyncSession, payload: dict) -> None:
    """Job handler for `reflow_plan`."""
    await reflow_plan_slots(session, payload["plan_id"])


async def enqueue_reflow_for_subject(session: AsyncSession, subject_id: int) -> int:
    """Queue one reflow per plan (draft and accepted) of every class on the
    subject, within the subject's own organization (`SEC-7`).
    The caller commits. Returns how many jobs were queued."""
    subject = await session.get(Subject, subject_id)
    if subject is None or subject.organization_id is None:
        return 0
    plan_ids = list(
        (
            await session.scalars(
                select(TeachingPlan.id)
                .join(Group, Group.id == TeachingPlan.group_id)
                .where(
                    Group.subject_id == subject_id,
                    Group.organization_id == subject.organization_id,
                    TeachingPlan.organization_id == subject.organization_id,
                )
                .order_by(TeachingPlan.id)
            )
        ).all()
    )
    if not plan_ids:
        return 0
    # One job per plan per call, never deduped against a pending one. A skipped
    # enqueue can lose an edit: the pending job may be claimed and read the
    # chapters before this caller's commit lands. The job is mechanical and
    # idempotent, so a duplicate run costs nothing and a lost one is a stale plan.
    queued = 0
    for plan_id in plan_ids:
        await enqueue(session, PLAN_REFLOW_JOB, {"plan_id": plan_id})
        queued += 1
    return queued
