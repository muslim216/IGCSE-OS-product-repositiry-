"""DB-backed background jobs and the worker that runs them.

Jobs are persisted so nothing is lost on restart. Handlers are registered in a
dict by job type; the worker loop claims the oldest pending job, runs it, and
records success or failure (with one retry). Tests call process_one_job()
directly instead of running the loop.

The worker can run inside the API process (today's deployment) or as its own
service (`python -m app.workers`, task 1.3) — the claim query has always been
safe for both, and since 1.3 the liveness clocks live in the database rather
than in this module's memory, so the API can report on a worker it does not
contain.
"""

import asyncio
import contextlib
import logging
import os
import secrets
import traceback
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import async_session
from app.models import Job, JobStatus, WorkerHeartbeat

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

#: A worker that raises on every iteration is restarted by the supervisor every
#: WORKER_RESTART_SECONDS, and each restart re-stamps _last_loop_at — so without
#: counting restarts a crash loop is indistinguishable from a healthy worker,
#: which is the one condition readiness exists to expose. One restart is the
#: supervisor doing its job; several inside the window is a loop that cannot
#: survive itself, and no job will ever complete.
CRASH_LOOP_WINDOW_SECONDS = 300.0
CRASH_LOOP_THRESHOLD = 3

Handler = Callable[[AsyncSession, dict], Awaitable[None]]
_handlers: dict[str, Handler] = {}

#: This process's worker identity. Generated per process, not per machine: a
#: restarted process is a new worker with its own row, which is what makes a
#: worker that vanished visible as a row that stopped updating rather than one
#: that silently changed meaning. The pid prefix is for a human reading the
#: table; the random suffix is what makes it unique across hosts.
WORKER_ID = f"{os.getpid()}-{secrets.token_hex(8)}"

#: How often the loop clock is written. The loop turns every POLL_SECONDS (2s),
#: but STALE_AFTER_SECONDS is 120 — writing on every iteration would be 30
#: writes a minute per worker to say nothing new. Job start and end are written
#: immediately regardless, because those are events rather than a clock.
HEARTBEAT_INTERVAL_SECONDS = 10.0

#: A heartbeat row this far past its last loop belongs to a process that is
#: gone, not one that is slow — several times STALE_AFTER_SECONDS. Pruned when a
#: worker registers rather than on every iteration: rows only accumulate when a
#: worker restarts, so that is exactly when cleaning up is proportional.
HEARTBEAT_REAP_SECONDS = 3600.0

#: Whether this process is actually running a worker. False under the test
#: client and when a test drives process_one_job() directly (`QA-6`), which must
#: not register a heartbeat — doing so would make `not_started` unreachable in
#: tests and turn every suite run into a fake worker.
_worker_registered = False

#: Ceiling on any single heartbeat write. These run on the worker's own path —
#: including the supervisor's restart record — so an unbounded wait on an
#: exhausted pool would delay the work itself for pool_timeout to record
#: telemetry about it. Losing a heartbeat is cheap; stalling the worker is not.
HEARTBEAT_WRITE_TIMEOUT_SECONDS = 5.0

#: Throttle for the loop clock; see HEARTBEAT_INTERVAL_SECONDS.
_last_heartbeat_write: datetime | None = None


async def _write_heartbeat(**fields) -> None:
    """Update this worker's row. Never raises.

    A worker that cannot write its heartbeat is still a worker that can do
    work, and the database being briefly unreachable must not take down job
    processing — the heartbeat is a report about the worker, not a dependency
    of it.
    """
    if not _worker_registered:
        return
    try:
        async with async_session() as session:
            row = await session.scalar(
                select(WorkerHeartbeat).where(WorkerHeartbeat.worker_id == WORKER_ID)
            )
            if row is None:
                return
            for key, value in fields.items():
                setattr(row, key, value)
            await session.commit()
    except Exception:  # noqa: BLE001 — telemetry must not break the worker
        log.exception("could not write worker heartbeat")


async def register_worker(now: datetime | None = None) -> None:
    """Claim this process's heartbeat row and clear out dead ones."""
    global _worker_registered
    now = now or datetime.now(timezone.utc)
    try:
        async with async_session() as session:
            await session.execute(
                delete(WorkerHeartbeat).where(
                    WorkerHeartbeat.last_loop_at < now - timedelta(seconds=HEARTBEAT_REAP_SECONDS)
                )
            )
            row = await session.scalar(
                select(WorkerHeartbeat).where(WorkerHeartbeat.worker_id == WORKER_ID)
            )
            if row is None:
                row = WorkerHeartbeat(worker_id=WORKER_ID, restarts=[])
                session.add(row)
            row.started_at = now
            row.last_loop_at = now
            row.job_started_at = None
            await session.commit()
        _worker_registered = True
    except Exception:  # noqa: BLE001 — see _write_heartbeat
        log.exception("could not register worker heartbeat")


async def note_worker_restart(now: datetime | None = None) -> None:
    """Record that the supervisor had to restart the loop.

    Called by the supervisor rather than by worker_loop() itself, because the
    thing worth counting is the restart, and worker_loop() has already died by
    the time one happens.

    The list is pruned to the crash-loop window on write, which is what keeps
    it bounded now that it is a JSON column rather than a bounded deque.
    """
    now = now or datetime.now(timezone.utc)
    if not _worker_registered:
        return

    async def _record() -> None:
        async with async_session() as session:
            row = await session.scalar(
                select(WorkerHeartbeat).where(WorkerHeartbeat.worker_id == WORKER_ID)
            )
            if row is None:
                return
            cutoff = now - timedelta(seconds=CRASH_LOOP_WINDOW_SECONDS)
            kept = [t for t in (row.restarts or []) if (p := _parse(t)) and p >= cutoff]
            kept.append(now.isoformat())
            # Reassigned rather than mutated in place: SQLAlchemy does not track
            # mutations inside a plain JSON column, so an .append() here would
            # be silently dropped at commit.
            row.restarts = kept
            await session.commit()

    # Shielded: this runs from the supervisor, which is exactly where a
    # shutdown cancellation lands. A restart recorded half-way is worse than
    # useless — it leaves a statement in flight on the connection — and the
    # write is a single short round trip, so letting it finish costs nothing
    # measurable at shutdown.
    #
    # Bounded as well as shielded: telemetry must not hold up a restart. If the
    # pool is exhausted, an unbounded acquire would block the supervisor for
    # pool_timeout instead of honouring WORKER_RESTART_SECONDS, delaying the
    # recovery this call exists to record.
    task = asyncio.ensure_future(_record())
    try:
        await asyncio.wait_for(asyncio.shield(task), timeout=HEARTBEAT_WRITE_TIMEOUT_SECONDS)
    except asyncio.CancelledError:
        # shield() re-raises the cancellation while `task` keeps running
        # underneath. Awaiting it before propagating is what stops an orphaned
        # write outliving this coroutine and finishing against a connection
        # nobody is watching.
        with contextlib.suppress(Exception):
            await task
        raise
    except TimeoutError:
        task.cancel()
        log.warning("worker restart record timed out; continuing without it")
    except Exception:  # noqa: BLE001 — see _write_heartbeat
        log.exception("could not record worker restart")


def _parse(value: str) -> datetime | None:
    try:
        return _aware(datetime.fromisoformat(value))
    except (TypeError, ValueError):
        return None


def _aware(value: datetime | None) -> datetime | None:
    """Attach UTC to a naive timestamp.

    SQLite hands back tz-naive datetimes for the same column Postgres returns
    aware, and subtracting one from the other raises. The stored value is UTC
    either way, so assuming UTC on a naive one is a read of the storage
    contract, not a guess. Same reasoning as `main._age_seconds`.
    """
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def register_handler(job_type: str, handler: Handler) -> None:
    _handlers[job_type] = handler


@dataclass(frozen=True)
class WorkerStatus:
    """A snapshot of whether background work is actually happening.

    `state` is the operator-facing answer:

    - `not_started` — no worker has registered. That is the normal state under
      the test client, which never enters the app's lifespan.
    - `unknown` — the heartbeat table could not be read, so nothing is known
      either way. Deliberately NOT healthy: reporting "no workers" when the
      real answer is "no idea" would return 200 for an unreadable database.
    - `running` — the loop completed an iteration recently, or is inside a job.
    - `crash_looping` — the supervisor has restarted the loop CRASH_LOOP_THRESHOLD
      times inside the window. The loop is alive and no work is getting done.
    - `stalled` — a single job has been in flight past JOB_STALL_SECONDS.
    - `stale` — the loop stopped completing iterations with nothing in flight.

    The timestamps are kept apart on purpose. A worker part-way through a slow
    AI call is healthy and a worker whose loop has stopped is not, and a single
    "last seen" clock cannot tell those apart — it would either page on every
    slow marking run or stay silent through a dead loop.

    `restarts` is the third clock, and it exists because the other two lie in one
    specific case: worker_loop() re-stamps _last_loop_at on entry, so a loop that
    raises immediately and is restarted every few seconds keeps a fresh
    timestamp and reports `running` forever while completing nothing.
    """

    state: str
    started_at: datetime | None
    last_loop_at: datetime | None
    seconds_since_loop: float | None
    job_running_seconds: float | None
    restarts_in_window: int
    last_restart_at: datetime | None

    @property
    def healthy(self) -> bool:
        return self.state in ("not_started", "running")


def _status_for(row: WorkerHeartbeat, now: datetime) -> WorkerStatus:
    """One worker's state. The rules are unchanged from when these clocks were
    module globals; only where they are read from has moved."""
    job_started_at = _aware(row.job_started_at)
    last_loop_at = _aware(row.last_loop_at)
    job_seconds = (now - job_started_at).total_seconds() if job_started_at else None
    loop_seconds = (now - last_loop_at).total_seconds() if last_loop_at else None

    window_start = now - timedelta(seconds=CRASH_LOOP_WINDOW_SECONDS)
    parsed = [d for d in (_parse(t) for t in (row.restarts or [])) if d is not None]
    recent_restarts = [d for d in parsed if d >= window_start]

    if len(recent_restarts) >= CRASH_LOOP_THRESHOLD:
        # Checked before the timestamp states on purpose: a crash loop presents
        # as `running`, so asking about liveness first would answer the wrong
        # question with the wrong answer.
        state = "crash_looping"
    elif job_seconds is not None:
        state = "stalled" if job_seconds > JOB_STALL_SECONDS else "running"
    elif loop_seconds is not None and loop_seconds > STALE_AFTER_SECONDS:
        state = "stale"
    else:
        state = "running"

    return WorkerStatus(
        state=state,
        started_at=_aware(row.started_at),
        last_loop_at=last_loop_at,
        seconds_since_loop=loop_seconds,
        job_running_seconds=job_seconds,
        restarts_in_window=len(recent_restarts),
        last_restart_at=max(parsed) if parsed else None,
    )


async def worker_status(now: datetime | None = None) -> WorkerStatus:
    """The state of background processing as a whole.

    With the worker split out (task 1.3) there can be several worker processes,
    so this reduces N rows to the one answer an operator wants: is work getting
    done? Any single healthy worker means yes, because the queue is shared and
    the claim is atomic — so a dying worker alongside a healthy one is not an
    outage. When nothing is healthy, the worst state is reported, since that is
    the one that explains why.

    No rows at all is `not_started`, which is the normal state under the test
    client and when a test drives process_one_job() directly — neither runs a
    worker, and a test run is not a broken deployment.
    """
    now = now or datetime.now(timezone.utc)
    try:
        async with async_session() as session:
            rows = list(await session.scalars(select(WorkerHeartbeat)))
    except Exception:  # noqa: BLE001 — reported as `unknown`, never as healthy
        # NOT the same as an empty table. "No workers" is a healthy answer
        # under the test client; "the query failed" is not an answer at all,
        # and collapsing the two would return 200 for a database this endpoint
        # could not read.
        log.exception("could not read worker heartbeats")
        return WorkerStatus(
            state="unknown",
            started_at=None,
            last_loop_at=None,
            seconds_since_loop=None,
            job_running_seconds=None,
            restarts_in_window=0,
            last_restart_at=None,
        )

    if not rows:
        return WorkerStatus(
            state="not_started",
            started_at=None,
            last_loop_at=None,
            seconds_since_loop=None,
            job_running_seconds=None,
            restarts_in_window=0,
            last_restart_at=None,
        )

    statuses = [_status_for(row, now) for row in rows]
    healthy = [s for s in statuses if s.state == "running"]
    if healthy:
        # The most recently active healthy worker, so the reported clocks belong
        # to a worker that is actually working.
        return max(healthy, key=lambda s: s.last_loop_at or now)
    # Nothing healthy: report the worst, ordered by how much it explains.
    severity = {"crash_looping": 3, "stalled": 2, "stale": 1}
    return max(statuses, key=lambda s: severity.get(s.state, 0))


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

    await _write_heartbeat(job_started_at=datetime.now(timezone.utc))
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
            assert job is not None
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
        await _write_heartbeat(job_started_at=None)
    return True


async def worker_loop() -> None:
    global _last_heartbeat_write
    await register_worker()
    log.info("job worker started (worker_id=%s)", WORKER_ID)
    while True:
        # Retried, not attempted once: a database that is unreachable at
        # startup would otherwise leave this worker permanently unregistered.
        # Jobs would resume the moment the database came back — the claim
        # query has its own connection — while readiness went on reporting
        # `not_started` forever, which is the one thing it exists not to do.
        if not _worker_registered:
            await register_worker()
        # Stamped before the claim, not after the work, so the timestamp answers
        # "is the loop turning?" rather than "did a job finish?" — an idle queue
        # and a dead loop otherwise look identical. Throttled to
        # HEARTBEAT_INTERVAL_SECONDS: the loop turns far faster than the
        # staleness threshold it feeds, so writing every iteration would cost
        # writes to say nothing new.
        now = datetime.now(timezone.utc)
        if (
            _last_heartbeat_write is None
            or (now - _last_heartbeat_write).total_seconds() >= HEARTBEAT_INTERVAL_SECONDS
        ):
            await _write_heartbeat(last_loop_at=now)
            _last_heartbeat_write = now
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
