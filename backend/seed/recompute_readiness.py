"""Queue a v2 readiness run for every (student, subject) that has evidence.

Usage (from backend/): python -m seed.recompute_readiness [--spacing SECONDS]

This is the backfill runner for task 0.2 (AV-29). Readiness snapshots are
append-only and only ever written by the `compute_readiness_v2` job, so when
the maths behind a factor changes — 0.1's settled-status fix, or any of
Phase 5's factor changes — existing snapshots keep reporting the old answer
until something re-runs them. Nothing does that on its own: a run is normally
triggered by new marks landing, and a student whose work is all marked already
would never be recomputed.

It queues jobs rather than computing inline, so every snapshot is written by
the same handler the product uses (no second code path), and a failed run
retries like any other job.

**Spacing is the point.** Each run is an AI call, so firing several hundred at
once would hit the provider's rate limit and bury real-time marking behind the
backfill. Pairs are queued with a steadily increasing `run_after`, which drains
the backlog at a predictable rate — roughly `3600 / spacing` runs an hour.

Safe to re-run: `enqueue_readiness_v2_debounced` skips a pair that already has
a pending job, so a second invocation while the first is still draining adds
nothing rather than doubling the queue.
"""

import argparse
import asyncio

from sqlalchemy import select

from app.config import get_settings
from app.db import async_session
from app.models import Evidence, Job, JobStatus, Topic
from app.services.readiness_v2_ai import enqueue_readiness_v2_debounced

#: Seconds between consecutive queued runs. The default drains 120 pairs an
#: hour, comfortably under the AI provider's limits while leaving headroom for
#: the marking traffic that shares the same worker.
DEFAULT_SPACING_SECONDS = 30


async def pairs_with_evidence(session) -> list[tuple[int, int]]:
    """Every (student_id, subject_id) that has at least one piece of evidence.

    Evidence hangs off a topic, not a subject, so the subject comes from the
    topic's own row. Ordered so a re-run queues in the same sequence.
    """
    rows = (
        await session.execute(
            select(Evidence.student_id, Topic.subject_id)
            .join(Topic, Topic.id == Evidence.topic_id)
            .distinct()
            .order_by(Evidence.student_id, Topic.subject_id)
        )
    ).all()
    return [(student_id, subject_id) for student_id, subject_id in rows]


async def already_pending(session) -> set[tuple[int, int]]:
    """The (student_id, subject_id) pairs that already have a run queued.

    `enqueue_readiness_v2_debounced` skips these on its own, but it does so
    silently and returns nothing either way. Reading them here lets the runner
    report a count that is actually true, and keeps the spacing contiguous:
    were skipped pairs still to consume a slot, a re-run over a mostly-queued
    backlog would schedule its handful of real jobs hours apart.

    The payload is a JSON column, so the comparison happens in Python — the
    same reason `enqueue_readiness_v2_debounced` does it that way.
    """
    payloads = (
        await session.scalars(
            select(Job.payload).where(
                Job.type == "compute_readiness_v2",
                Job.status == JobStatus.pending,
            )
        )
    ).all()
    return {
        (p["student_id"], p["subject_id"])
        for p in payloads
        if p.get("student_id") is not None and p.get("subject_id") is not None
    }


async def main(spacing_seconds: int = DEFAULT_SPACING_SECONDS) -> None:
    settings = get_settings()
    if not settings.readiness_v2_shadow_enabled:
        # The debounced enqueue is a no-op with the kill switch off, so the
        # runner would report success having queued nothing at all.
        print("READINESS_V2_SHADOW_ENABLED is off — no jobs queued. Turn it on and run again.")
        return

    async with async_session() as session:
        pairs = await pairs_with_evidence(session)
        if not pairs:
            print("No evidence found — nothing to recompute.")
            return

        pending = await already_pending(session)
        todo = [pair for pair in pairs if pair not in pending]

        for index, (student_id, subject_id) in enumerate(todo):
            await enqueue_readiness_v2_debounced(
                session,
                student_id=student_id,
                subject_id=subject_id,
                delay_seconds=index * spacing_seconds,
            )
        await session.commit()

    skipped = len(pairs) - len(todo)
    if not todo:
        print(f"All {len(pairs)} pairs already have a run queued — nothing to do.")
        return

    last_run_minutes = (len(todo) - 1) * spacing_seconds // 60
    noun = "run" if len(todo) == 1 else "runs"
    message = (
        f"Queued {len(todo)} readiness {noun} "
        f"({spacing_seconds}s apart; the last fires in ~{last_run_minutes} min)."
    )
    if skipped:
        message += f" Skipped {skipped} already queued."
    print(message)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--spacing",
        type=int,
        default=DEFAULT_SPACING_SECONDS,
        help=f"seconds between queued runs (default {DEFAULT_SPACING_SECONDS})",
    )
    args = parser.parse_args()
    asyncio.run(main(args.spacing))
