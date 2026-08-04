"""DB-backed background jobs with an in-process asyncio worker.

Jobs are persisted so nothing is lost on restart. Handlers are registered in a
dict by job type; the worker loop claims the oldest pending job, runs it, and
records success or failure (with one retry). Tests call process_one_job()
directly instead of running the loop.
"""

import asyncio
import logging
import traceback
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import async_session
from app.models import Job, JobStatus

log = logging.getLogger("jobs")

MAX_ATTEMPTS = 2
POLL_SECONDS = 2.0

#: Wait before a failed job's second attempt. Without it the retry is claimed on
#: the next poll ~2s later, so both attempts are spent inside a few seconds —
#: exactly wrong for the provider rate limits and timeouts that retries exist to
#: survive. `run_after` is the same primitive readiness debouncing already uses.
RETRY_BACKOFF_SECONDS = 60.0

#: How long the loop may go without completing an iteration before it is
#: reported dead. The loop sleeps POLL_SECONDS when idle, so anything beyond a
#: few multiples of that means it stopped rather than that it is quiet.
STALE_AFTER_SECONDS = 120.0

#: A single job running longer than this is treated as hung. Marking is the
#: slowest handler and runs in tens of seconds; a quarter of an hour is not slow,
#: it is stuck — and a stuck job blocks the queue behind it just as a dead loop
#: would.
JOB_STALL_SECONDS = 900.0

Handler = Callable[[AsyncSession, dict], Awaitable[None]]
_handlers: dict[str, Handler] = {}

#: Worker liveness, read by the readiness endpoint. Plain module state is
#: sufficient and correct because the worker is a single asyncio task in a single
#: process — the same constraint that pins the API to one instance (RISK-1). If
#: the worker ever moves to its own service these have to move into the database
#: with it.
_started_at: datetime | None = None
_last_loop_at: datetime | None = None
_job_started_at: datetime | None = None


def register_handler(job_type: str, handler: Handler) -> None:
    _handlers[job_type] = handler


@dataclass(frozen=True)
class WorkerStatus:
    """A snapshot of whether background work is actually happening.

    `state` is the operator-facing answer:

    - `not_started` — worker_loop() has never run in this process. That is the
      normal state under the test client, which never enters the app's lifespan.
    - `running` — the loop completed an iteration recently, or is inside a job.
    - `stalled` — a single job has been in flight past JOB_STALL_SECONDS.
    - `stale` — the loop stopped completing iterations with nothing in flight.

    The two timestamps are kept apart on purpose. A worker part-way through a
    slow AI call is healthy and a worker whose loop has stopped is not, and a
    single "last seen" clock cannot tell those apart — it would either page on
    every slow marking run or stay silent through a dead loop.
    """

    state: str
    started_at: datetime | None
    last_loop_at: datetime | None
    seconds_since_loop: float | None
    job_running_seconds: float | None

    @property
    def healthy(self) -> bool:
        return self.state in ("not_started", "running")


def worker_status(now: datetime | None = None) -> WorkerStatus:
    now = now or datetime.now(timezone.utc)
    job_seconds = (now - _job_started_at).total_seconds() if _job_started_at else None
    loop_seconds = (now - _last_loop_at).total_seconds() if _last_loop_at else None

    if _started_at is None:
        state = "not_started"
    elif job_seconds is not None:
        state = "stalled" if job_seconds > JOB_STALL_SECONDS else "running"
    elif loop_seconds is not None and loop_seconds > STALE_AFTER_SECONDS:
        state = "stale"
    else:
        state = "running"

    return WorkerStatus(
        state=state,
        started_at=_started_at,
        last_loop_at=_last_loop_at,
        seconds_since_loop=loop_seconds,
        job_running_seconds=job_seconds,
    )


async def enqueue(
    session: AsyncSession,
    job_type: str,
    payload: dict,
    run_after: datetime | None = None,
) -> Job:
    """Queue a job. `run_after` delays it until that time — callers use it to
    batch bursty work (see readiness_v2_ai.enqueue_readiness_v2_debounced)."""
    job = Job(type=job_type, payload=payload, run_after=run_after)
    session.add(job)
    await session.flush()
    return job


async def process_one_job() -> bool:
    """Claim and run one due pending job. Returns False when nothing is due."""
    global _job_started_at
    now = datetime.now(timezone.utc)
    async with async_session() as session:
        job = await session.scalar(
            select(Job)
            .where(
                Job.status == JobStatus.pending,
                or_(Job.run_after.is_(None), Job.run_after <= now),
            )
            .order_by(Job.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if job is None:
            return False
        job.status = JobStatus.running
        job.attempts += 1
        await session.commit()
        job_id, job_type, payload, attempts = job.id, job.type, job.payload, job.attempts

    _job_started_at = datetime.now(timezone.utc)
    try:
        handler = _handlers.get(job_type)
        error: str | None = None
        if handler is None:
            error = f"No handler registered for job type '{job_type}'"
        else:
            try:
                async with async_session() as session:
                    await handler(session, payload)
                    await session.commit()
            except Exception as exc:  # noqa: BLE001 — worker must survive any job error
                log.error(
                    "job %s (%s) failed: %s\n%s", job_id, job_type, exc, traceback.format_exc()
                )
                error = str(exc) or exc.__class__.__name__

        async with async_session() as session:
            job = await session.get(Job, job_id)
            if error is None:
                job.status = JobStatus.done
                job.error = None
            elif attempts < MAX_ATTEMPTS:
                job.status = JobStatus.pending  # retry
                # Held back rather than re-claimed on the next poll: see
                # RETRY_BACKOFF_SECONDS. Handlers are required to be safe to
                # re-run on the same payload (BE-6), so the only question a
                # retry answers is whether the *cause* has passed, and two
                # attempts two seconds apart never gives it the chance to.
                job.run_after = datetime.now(timezone.utc) + timedelta(
                    seconds=RETRY_BACKOFF_SECONDS
                )
                job.error = error
            else:
                job.status = JobStatus.failed
                job.error = error
                # Nothing watches the failed count yet, so this line is the only
                # record that a piece of a student's work stopped moving.
                log.error(
                    "job %s (%s) gave up after %s attempts: %s", job_id, job_type, attempts, error
                )
            await session.commit()
    finally:
        _job_started_at = None
    return True


async def worker_loop() -> None:
    global _started_at, _last_loop_at
    _started_at = datetime.now(timezone.utc)
    log.info("job worker started")
    while True:
        # Stamped before the claim, not after the work, so the timestamp answers
        # "is the loop turning?" rather than "did a job finish?" — an idle queue
        # and a dead loop otherwise look identical.
        _last_loop_at = datetime.now(timezone.utc)
        try:
            worked = await process_one_job()
        except asyncio.CancelledError:
            log.info("job worker stopped")
            raise
        except Exception:  # noqa: BLE001
            log.exception("job worker iteration crashed")
            worked = False
        if not worked:
            await asyncio.sleep(POLL_SECONDS)
