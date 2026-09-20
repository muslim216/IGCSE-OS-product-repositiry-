"""Queue a tag_mistakes job for every settled submission that predates task 6.

Usage (from backend/): python -m seed.backfill_mistakes [--spacing SECONDS]

Manual, never automatic (decision 12) — unlike recompute_readiness, nothing
about tagging is a kill-switched shadow feature, so this script is the only
way tagging ever reaches a submission that settled before `record_marks_as_
evidence` started enqueuing it in the same change.

It queues jobs rather than tagging inline, so every Mistake row is written by
the same handler the product uses (no second code path). Safe to re-run, on two
levels: `settled_submission_ids` selects only submissions nothing has examined
yet, so a second invocation after the first has drained queues nothing at all;
and `already_queued` excludes anything with a pending or running job, so a
second invocation *while* the first is draining does not double the queue.
Both matter because each queued job is a paid AI call. The handler itself is
idempotent (BE-6), replacing only its own AI-sourced rows, so a double-queue
that slips past both is still not a correctness hazard — only wasted spend.

**Spacing is the point.** Each run is an AI call, so firing several hundred at
once would hit the provider's rate limit and bury real-time marking behind the
backfill. Pairs are queued with a steadily increasing `run_after`, which drains
the backlog at a predictable rate — roughly `3600 / spacing` runs an hour. This
rationale and the spacing constant are carried from seed/recompute_readiness.py,
which this module is modelled on.

**Known limitation:** the worker claims due jobs in `Job.id` order
(`workers/jobs.py`'s `process_one_job`), not by `run_after` or job type. If the
worker falls behind — a long outage, a burst of restarts — every backfill job
whose `run_after` has since passed becomes due at once and, having the lower
id, is claimed ahead of a real-time marking job queued after it. Spacing
controls the steady-state rate; it doesn't give real-time work priority once
the queue is already backed up.
"""

import argparse
import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.db import async_session
from app.models import Job, JobStatus, QuestionMark, Submission
from app.workers.jobs import enqueue

#: Seconds between consecutive queued runs. The default drains 120 submissions
#: an hour, comfortably under the AI provider's limits while leaving headroom
#: for the marking traffic that shares the same worker.
DEFAULT_SPACING_SECONDS = 30


async def settled_submission_ids(session) -> list[int]:
    """Every settled submission nothing has examined yet. There is no
    `finalized` column — settled means QuestionMark.final_marks is not None.

    `mistakes_analysed_at IS NULL` is what makes this module's name true: the
    set it exists to cover is the corpus that predates the `record_marks_as_
    evidence` enqueue, and a submission the job has already examined is not in
    it. Without the filter a second invocation re-queues **every** settled
    submission — `already_queued` below only sees pending and running jobs, not
    finished ones — and each of those is a paid AI call re-spent to reach the
    answer already stored (`PROD-1`: the run is traceable, so re-deriving it is
    waste, not evidence).

    The tradeoff: a submission examined while its subject had no categories
    also carries `mistakes_analysed_at` (`services/mistake_tagging.py`), so if
    the tutor writes their list afterwards this skips it. That is the tutor's
    own re-tag to press in 4.3, not something a backfill should guess at — and
    re-running with the filter lifted is a one-line edit somebody can make
    deliberately, which is the right shape for an operation that spends money.
    """
    rows = (
        await session.execute(
            select(QuestionMark.submission_id)
            .join(Submission, Submission.id == QuestionMark.submission_id)
            .where(
                QuestionMark.final_marks.is_not(None),
                Submission.mistakes_analysed_at.is_(None),
            )
            .distinct()
            .order_by(QuestionMark.submission_id)
        )
    ).all()
    return [submission_id for (submission_id,) in rows]


async def already_queued(session, submission_ids: list[int]) -> set[int]:
    """Submission ids already covered by a pending or running tag_mistakes job."""
    rows = (
        await session.execute(
            select(Job.payload).where(
                Job.type == "tag_mistakes",
                Job.status.in_((JobStatus.pending, JobStatus.running)),
            )
        )
    ).all()
    queued = {payload.get("submission_id") for (payload,) in rows}
    return queued & set(submission_ids)


async def main(spacing_seconds: int = DEFAULT_SPACING_SECONDS) -> None:
    if spacing_seconds <= 0:
        # Zero or negative collapses every `run_after` to "now" (or the past),
        # defeating the rate-limit protection this whole module exists for.
        raise SystemExit(f"--spacing must be a positive number of seconds, got {spacing_seconds}")

    async with async_session() as session:
        submission_ids = await settled_submission_ids(session)
        if not submission_ids:
            print("No unexamined settled submissions found — nothing to backfill.")
            return

        pending = await already_queued(session, submission_ids)
        todo = [sid for sid in submission_ids if sid not in pending]

        now = datetime.now(timezone.utc)
        for index, submission_id in enumerate(todo):
            await enqueue(
                session,
                "tag_mistakes",
                {"submission_id": submission_id},
                run_after=now + timedelta(seconds=index * spacing_seconds),
            )
        await session.commit()

    skipped = len(submission_ids) - len(todo)
    if not todo:
        print(f"All {len(submission_ids)} settled submissions already queued — nothing to do.")
        return

    last_run_minutes = (len(todo) - 1) * spacing_seconds // 60
    noun = "job" if len(todo) == 1 else "jobs"
    message = (
        f"Queued {len(todo)} tag_mistakes {noun} "
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
