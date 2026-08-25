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

Safe to re-run: `already_pending()` below excludes any pair with a pending or
running job before this module ever calls `enqueue_readiness_v2_debounced`
(which only catches `pending` on its own), so a second invocation while the
first is still draining adds nothing rather than doubling the queue.
"""

import argparse
import asyncio

from sqlalchemy import select

from app.config import get_settings
from app.db import async_session
from app.models import Evidence, Topic
from app.services.readiness_summary_v2 import _IN_FLIGHT
from app.services.readiness_v2_ai import enqueue_readiness_v2_debounced, in_flight_readiness_pairs

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


async def already_pending(session, pairs: list[tuple[int, int]]) -> set[tuple[int, int]]:
    """The (student_id, subject_id) pairs from `pairs` already covered by a
    queued or running run.

    `enqueue_readiness_v2_debounced` skips these on its own, but it does so
    silently and returns nothing either way, and only checks `pending` — a job
    that is already `running` isn't in its window, so re-running this script
    while a backfill job is actively executing would still re-queue it.
    Reading both statuses here (the same `_IN_FLIGHT` pair the readiness
    summary uses to show "recalculating") lets the runner report a count that
    is actually true, and keeps the spacing contiguous: were skipped pairs
    still to consume a slot, a re-run over a mostly-queued backlog would
    schedule its handful of real jobs hours apart.

    A job queued with `subject_id: None` covers every subject the student is
    enrolled in (`compute_readiness_v2`'s own contract) — not just the one
    pair it happens to share a payload shape with — so it must count as
    covering every pair for that student, not just a (student_id, None) pair
    that would never itself appear in `pairs`.

    Reads through `in_flight_readiness_pairs()`, the one place this query
    lives — `enqueue_readiness_v2_debounced` and the readiness summary's
    "recalculating" check use it too, so a payload-shape or status-set change
    can't drift between the three.
    """
    in_flight = await in_flight_readiness_pairs(session, _IN_FLIGHT)
    exact = {(sid, subj) for sid, subj in in_flight if subj is not None}
    wildcard_students = {sid for sid, subj in in_flight if subj is None}
    return exact | {pair for pair in pairs if pair[0] in wildcard_students}


async def main(spacing_seconds: int = DEFAULT_SPACING_SECONDS) -> None:
    if spacing_seconds <= 0:
        # Zero or negative collapses every `run_after` to "now" (or the past),
        # defeating the rate-limit protection this whole module exists for.
        raise SystemExit(f"--spacing must be a positive number of seconds, got {spacing_seconds}")

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

        pending = await already_pending(session, pairs)
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
