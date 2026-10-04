"""Recompute readiness the day a class's past-paper phase opens (AV-31, Phase 7).

The AV-31 gate (`readiness_factors.past_paper_phase_started`) counts past-paper
evidence only once a class's accepted plan has `past_paper_start_date <= today`.
Readiness recomputes only when new evidence arrives, so the day that date
passes nothing recomputes and the student's readiness keeps omitting past-paper
performance until something unrelated lands. No readiness maths changes here:
this only queues the ordinary debounced v2 run at the right moment.

The sweep re-derives who needs a run from the database every time (BE-9), so it
is self-healing — a missed day is caught on the next sweep — and idempotent
(BE-6): once a pair has a snapshot written on or after its start date it drops
out, and a pair with a run already pending is skipped by the debounce.

The reliability shape is copied from the parent-narrative sweep: the successor
is committed in its own transaction before any work, so a failing run cannot
kill the schedule.
"""

import logging
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import async_session
from app.models import (
    AiSynthesisStatus,
    FactorEvaluation,
    Group,
    GroupMember,
    Job,
    JobStatus,
    PastPaper,
    PastPaperAttempt,
    ReadinessFactor,
    ReadinessSnapshot,
    TeachingPlan,
    TeachingPlanStatus,
)
from app.services.readiness_v2_ai import in_flight_readiness_pairs
from app.workers.jobs import enqueue

log = logging.getLogger("past_paper_phase")

SWEEP_JOB = "sweep_past_paper_phase"

# Each queued run is an AI synthesis call; a class whose phase opens has many
# students at once. Spacing them keeps the batch from firing as one burst (same
# idea as seed/recompute_readiness.py).
RECOMPUTE_SPACING_SECONDS = 30


def _aware(value: datetime) -> datetime:
    # SQLite returns tz-naive datetimes where Postgres returns aware ones.
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


async def pairs_needing_phase_recompute(
    session: AsyncSession, today: date
) -> list[tuple[int, int]]:
    """(student_id, subject_id) pairs whose readiness predates the opening of
    the past-paper phase and which actually have past-paper evidence to reveal.

    A fixed handful of grouped queries however many students there are (PERF-1). Organization
    scoping comes from the joins: the plan must belong to the same organization
    as its class, and the paper to the same organization as the class, so a
    subject shared by name across tenants never mixes (SEC-8).
    """
    # Earliest start date across a pair's classes whose phase has opened: the
    # gate opens as soon as any one class says so.
    opened = (
        await session.execute(
            select(
                GroupMember.student_id,
                Group.subject_id,
                func.min(TeachingPlan.past_paper_start_date),
            )
            .select_from(GroupMember)
            .join(Group, Group.id == GroupMember.group_id)
            .join(
                TeachingPlan,
                (TeachingPlan.group_id == Group.id)
                & (TeachingPlan.organization_id == Group.organization_id)
                & (TeachingPlan.status == TeachingPlanStatus.accepted),
            )
            .where(
                TeachingPlan.past_paper_start_date.is_not(None),
                TeachingPlan.past_paper_start_date <= today,
                # Evidence the factor would actually score: a marked attempt on
                # a paper of the same tenant and subject. Without it the gate
                # opening changes nothing and a run is a wasted AI call.
                select(PastPaperAttempt.id)
                .join(PastPaper, PastPaper.id == PastPaperAttempt.past_paper_id)
                .where(
                    PastPaperAttempt.student_id == GroupMember.student_id,
                    PastPaper.subject_id == Group.subject_id,
                    PastPaper.organization_id == Group.organization_id,
                    PastPaperAttempt.raw_marks.is_not(None),
                    PastPaperAttempt.max_marks > 0,
                )
                .exists(),
            )
            .group_by(GroupMember.student_id, Group.subject_id)
            .order_by(GroupMember.student_id, Group.subject_id)
        )
    ).all()
    if not opened:
        return []

    students = {row[0] for row in opened}
    # A pair is fresh only if its latest READY run's gate said the phase had
    # started. Not a timestamp comparison: a run that read the date before the
    # start but finished after midnight is newer than the start yet never saw
    # the phase open. A `failed` run (AI outage) leaves no score a student can
    # read, so it never counts either; retrying is bounded to one run per pair
    # per sweep interval. Rows written before `phase_started` existed lack the
    # key and count as not fresh: one recompute, after which they carry it.
    newest_ready = (
        select(func.max(ReadinessSnapshot.id))
        .where(
            ReadinessSnapshot.student_id.in_(students),
            ReadinessSnapshot.status == AiSynthesisStatus.ready,
        )
        .group_by(ReadinessSnapshot.student_id, ReadinessSnapshot.subject_id)
    )
    run_ids = {
        (student_id, subject_id): run_id
        for student_id, subject_id, run_id in (
            await session.execute(
                select(
                    ReadinessSnapshot.student_id,
                    ReadinessSnapshot.subject_id,
                    ReadinessSnapshot.evaluation_run_id,
                ).where(ReadinessSnapshot.id.in_(newest_ready))
            )
        ).all()
    }
    # `detail` is generic JSON (DB-7), so it is read in Python rather than
    # filtered in SQL, which would differ between SQLite and Postgres.
    saw_phase_open: set[str] = set()
    if run_ids:
        for run_id, detail in (
            await session.execute(
                select(FactorEvaluation.evaluation_run_id, FactorEvaluation.detail).where(
                    FactorEvaluation.evaluation_run_id.in_(set(run_ids.values())),
                    FactorEvaluation.factor == ReadinessFactor.past_paper_performance,
                )
            )
        ).all():
            if isinstance(detail, dict) and detail.get("phase_started") is True:
                saw_phase_open.add(run_id)

    failed_at: dict[tuple[int, int], datetime] = {
        (student_id, subject_id): _aware(created)
        for student_id, subject_id, created in (
            await session.execute(
                select(
                    ReadinessSnapshot.student_id,
                    ReadinessSnapshot.subject_id,
                    func.max(ReadinessSnapshot.created_at),
                )
                .where(
                    ReadinessSnapshot.student_id.in_(students),
                    ReadinessSnapshot.status == AiSynthesisStatus.failed,
                )
                .group_by(ReadinessSnapshot.student_id, ReadinessSnapshot.subject_id)
            )
        ).all()
    }

    due: list[tuple[int, int]] = []
    for student_id, subject_id, start in opened:
        if run_ids.get((student_id, subject_id)) in saw_phase_open:
            continue
        due.append((student_id, subject_id))
        failed_when = failed_at.get((student_id, subject_id))
        if failed_when is not None and failed_when >= datetime.combine(
            start, time.min, tzinfo=timezone.utc
        ):
            log.warning(
                "past-paper phase recompute retried after a failed run: student=%s subject=%s",
                student_id,
                subject_id,
            )
    return due


async def _pending_sweep_exists(session: AsyncSession) -> bool:
    return (
        await session.scalar(
            select(func.count(Job.id)).where(Job.type == SWEEP_JOB, Job.status == JobStatus.pending)
        )
        or 0
    ) > 0


async def ensure_past_paper_phase_sweep_scheduled(session: AsyncSession) -> None:
    """Startup floor: if no sweep is pending, schedule one. Idempotent."""
    if await _pending_sweep_exists(session):
        return
    await enqueue(session, SWEEP_JOB, {})


async def _commit_successor_sweep() -> None:
    """Queue the next sweep in its own committed transaction, so it survives
    the handler's session rolling back when the body raises (see narrative's
    `_commit_successor_sweep` for the full reasoning)."""
    async with async_session() as session:
        if await _pending_sweep_exists(session):
            return
        interval = get_settings().past_paper_phase_sweep_interval_hours
        await enqueue(
            session,
            SWEEP_JOB,
            {},
            run_after=datetime.now(timezone.utc) + timedelta(hours=interval),
        )
        await session.commit()


async def sweep_past_paper_phase(session: AsyncSession, payload: dict) -> None:
    """Queue a v2 readiness run for every pair whose past-paper phase has opened
    since its last run. Payload is `{}`; everything is re-derived (BE-9)."""
    await _commit_successor_sweep()
    settings = get_settings()
    # The schedule is already re-armed, so flipping the kill switch back on
    # resumes without a restart.
    if not settings.readiness_v2_shadow_enabled:
        log.info("past-paper phase sweep: readiness v2 kill switch is off, nothing queued")
        return
    today = datetime.now(timezone.utc).date()
    pairs = await pairs_needing_phase_recompute(session, today)
    # Read once, not per pair (PERF-1). A running job counts as covering: if it
    # began before the phase opened its snapshot is dated after the start, and
    # if it somehow used the old gate the next sweep re-checks. Selection needs
    # an accepted plan, so a class without one is never queued; a plan revoked
    # between selection and run costs at most one redundant run, which
    # self-heals because the pair is re-derived every sweep.
    covered_students: set[int] = set()
    covered_pairs: set[tuple[int, int]] = set()
    for sid, subj in await in_flight_readiness_pairs(
        session, (JobStatus.pending, JobStatus.running)
    ):
        if subj is None:
            covered_students.add(sid)  # a wildcard job covers every subject
        else:
            covered_pairs.add((sid, subj))
    queued = 0
    skipped = 0
    for student_id, subject_id in pairs:
        if student_id in covered_students or (student_id, subject_id) in covered_pairs:
            skipped += 1
            continue
        delay = settings.readiness_v2_coalesce_seconds + queued * RECOMPUTE_SPACING_SECONDS
        await enqueue(
            session,
            "compute_readiness_v2",
            {"student_id": student_id, "subject_id": subject_id},
            run_after=datetime.now(timezone.utc) + timedelta(seconds=delay),
        )
        queued += 1
    log.info(
        "past-paper phase sweep: %d pairs found, %d queued, %d skipped (already in flight)",
        len(pairs),
        queued,
        skipped,
    )
