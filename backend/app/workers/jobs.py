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
from datetime import datetime, timezone

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import async_session
from app.models import Job, JobStatus

log = logging.getLogger("jobs")

MAX_ATTEMPTS = 2
POLL_SECONDS = 2.0

Handler = Callable[[AsyncSession, dict], Awaitable[None]]
_handlers: dict[str, Handler] = {}


def register_handler(job_type: str, handler: Handler) -> None:
    _handlers[job_type] = handler


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
            log.error("job %s (%s) failed: %s\n%s", job_id, job_type, exc, traceback.format_exc())
            error = str(exc) or exc.__class__.__name__

    async with async_session() as session:
        job = await session.get(Job, job_id)
        if error is None:
            job.status = JobStatus.done
            job.error = None
        elif attempts < MAX_ATTEMPTS:
            job.status = JobStatus.pending  # retry
            job.error = error
        else:
            job.status = JobStatus.failed
            job.error = error
        await session.commit()
    return True


async def worker_loop() -> None:
    log.info("job worker started")
    while True:
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
