"""DB-backed background jobs and the worker that runs them.

Jobs are persisted so nothing is lost on restart. Handlers are registered in a
dict by job type; the worker loop claims the oldest pending job, runs it, and
records success or failure (with one retry, unless the failure says a retry
cannot help: see `is_permanent`). A handler that runs past its time limit is
stopped (`job_timeout_seconds`). Tests call process_one_job() directly instead
of running the loop.

The worker can run inside the API process (today's deployment) or as its own
service (`python -m app.workers`, task 1.3) — the claim query has always been
safe for both, and since 1.3 the liveness clocks live in the database rather
than in this module's memory, so the API can report on a worker it does not
contain.
"""

import asyncio
import contextlib
import logging
import math
import os
import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
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

#: How far above the AI deadline a job's time limit sits (see
#: `job_timeout_seconds`): room to read the uploaded files before the call and
#: to write the result after it.
JOB_TIMEOUT_MARGIN_SECONDS = 60.0

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
#: What a job type does when the worker gives up on one of its jobs: see
#: `register_handler` and `_tell_handler_it_was_given_up`.
GiveUp = Callable[[AsyncSession, dict, str], Awaitable[None]]
_give_ups: dict[str, GiveUp] = {}
#: What a row is marked with when the worker holding its job died on the last
#: attempt (a deploy or a crash mid-job, twice).
ORPHANED_MESSAGE = "The server restarted while this was being worked on, so it was not finished"
#: Ceiling on one give-up call. It is a single small write, made on the worker's
#: own path after a job has already failed; it must not become the next hang.
GIVE_UP_TIMEOUT_SECONDS = 30.0
#: Job types whose time limit is not the default one. Kept beside
#: `_handlers` rather than inside it so that dict stays what tests and callers
#: already treat it as: job type -> handler.
_timeouts: dict[str, float] = {}

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

#: How old a claim must be before the orphan sweep will look at it (task 1.5,
#: AV-84). Deliberately **above** HEARTBEAT_REAP_SECONDS, and that ordering is
#: the whole safety argument.
#:
#: The sweep's signal is "the claiming worker has no heartbeat row". A dead
#: worker's row is reaped, so that reads correctly for the case this exists for.
#: But `register_worker()` can also reap a *live* worker's row — one whose job
#: has been in flight past HEARTBEAT_REAP_SECONDS, because at that point a job
#: in flight is indistinguishable from a process that died holding one (§3.4's
#: accepted residual). That worker is row-less until its next heartbeat write,
#: which for a process inside a long job does not come until the job ends.
#:
#: Requeueing there would run a handler that is still running — the duplicate
#: side effect this whole suite exists to prevent. Waiting twice the reap window
#: means a claim is only ever reclaimed long past the point where anything
#: legitimately holds a job.
ORPHAN_RECLAIM_SECONDS = 2 * HEARTBEAT_REAP_SECONDS

#: How often the orphan sweep runs. Rare on purpose: it is a repair path, not a
#: control loop, and the rows it looks for are minted only by a process dying.
ORPHAN_SWEEP_INTERVAL_SECONDS = 300.0

#: Throttle for the orphan sweep; see ORPHAN_SWEEP_INTERVAL_SECONDS.
_last_orphan_sweep: datetime | None = None


async def _write_heartbeat(**fields) -> None:
    """Update this worker's row. Never raises.

    A worker that cannot write its heartbeat is still a worker that can do
    work, and the database being briefly unreachable must not take down job
    processing — the heartbeat is a report about the worker, not a dependency
    of it.
    """
    global _worker_registered
    if not _worker_registered:
        return
    try:
        async with async_session() as session:
            row = await session.scalar(
                select(WorkerHeartbeat).where(WorkerHeartbeat.worker_id == WORKER_ID)
            )
            if row is None:
                # Our row is gone but we are demonstrably alive. That happens
                # when another worker's register_worker() reaps us: a job in
                # flight past HEARTBEAT_REAP_SECONDS is indistinguishable from
                # a process that died holding one, so the reap is right to be
                # aggressive — but the live worker must come back, not vanish.
                # Returning silently here would leave this process working
                # normally while absent from every health answer, which is the
                # invisible-worker failure (RISK-4) this table exists to end.
                # Clearing the flag hands it to worker_loop's existing
                # re-registration retry on the next iteration.
                _worker_registered = False
                log.warning("worker heartbeat row disappeared; will re-register")
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
                    or_(
                        # No job in flight: last_loop_at alone tells us the
                        # loop stopped turning, exactly as before.
                        (
                            WorkerHeartbeat.job_started_at.is_(None)
                            & (
                                WorkerHeartbeat.last_loop_at
                                < now - timedelta(seconds=HEARTBEAT_REAP_SECONDS)
                            )
                        ),
                        # A job in flight: a worker inside a single long job
                        # does not advance last_loop_at (see worker_loop()), so
                        # last_loop_at cannot be the test here — a live job
                        # past the default time limit must keep reporting `stalled`,
                        # not disappear. job_started_at itself is what a
                        # process killed mid-job leaves behind forever, so once
                        # a job has been "in flight" past the same
                        # HEARTBEAT_REAP_SECONDS window, that is no longer a
                        # slow job — nothing survives that long — it is a dead
                        # process's last row, and reaping it is what makes
                        # `register_worker` responsible for the case
                        # `worker_loop()` cannot detect from inside its own
                        # await.
                        (
                            WorkerHeartbeat.job_started_at.is_not(None)
                            & (
                                WorkerHeartbeat.job_started_at
                                < now - timedelta(seconds=HEARTBEAT_REAP_SECONDS)
                            )
                        ),
                    )
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
        with contextlib.suppress(Exception, asyncio.CancelledError):
            await task
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


def register_handler(
    job_type: str,
    handler: Handler,
    *,
    timeout_seconds: float | None = None,
    on_give_up: GiveUp | None = None,
) -> None:
    """Register `handler` for `job_type`. `timeout_seconds` replaces the
    default time limit (`job_timeout_seconds`) for a job that is known to need
    a different one; leaving it out also clears an override left by an earlier
    registration.

    `on_give_up(session, payload, error)` is called once whenever a job of this
    type ends `failed`, whichever way it got there. It exists for the two ways
    a job can fail without its handler knowing: stopped at the time limit (a
    cancellation, which no handler's `except Exception` sees) and orphaned by a
    worker that died with no attempts left. In both the row the job was working
    on is still in its "in progress" state with no error, and nothing else will
    ever move it. The hook's whole job is to end that: if the row is still in
    progress, mark it failed with `error`. It must leave alone a row the
    handler already marked, or one that has moved on since."""
    if timeout_seconds is not None and (timeout_seconds <= 0 or math.isnan(timeout_seconds)):
        # Zero, a negative or NaN would stop every run of the job the moment it
        # started, which reads as "the job is broken", not as a typo here. NaN
        # is named because it compares false to everything, `<= 0` included.
        raise ValueError(f"timeout_seconds for '{job_type}' must be above 0")
    _handlers[job_type] = handler
    if timeout_seconds is None:
        _timeouts.pop(job_type, None)
    else:
        _timeouts[job_type] = timeout_seconds
    if on_give_up is None:
        _give_ups.pop(job_type, None)
    else:
        _give_ups[job_type] = on_give_up


def job_timeout_seconds(job_type: str) -> float:
    """How long one run of `job_type` may take before the worker stops it and
    counts the job as a failed attempt.

    Until this existed nothing acted on a hung job: with one worker, a handler
    that never returned stopped every job behind it for good, and the only
    trace was the `stalled` state on /health/ready.

    The limit is **derived from the AI deadline**, never a number of its own,
    because it must always be the longer of the two. The AI deadline
    (`ai_call_timeout_seconds`) and every outbound HTTP timeout end as ordinary
    exceptions inside the handler, which is where a handler records a failure
    on the row it was working on. This limit arrives as a cancellation, which
    no handler's `except Exception` sees. So it is the backstop for a hang
    nothing else bounds, and a deployment that raises the AI deadline moves it
    too. It never drops below JOB_STALL_SECONDS, the point where health starts
    calling a job hung.

    What a stop leaves behind: the handler's writes are rolled back and the
    row it was working on stays as it was ("extracting", "generating", a
    submission still "submitted"). The first stop is retried, and the retry
    runs the handler again from the start. A second stop fails the job, and the
    job type's `on_give_up` hook then marks that row failed so it does not show
    as in progress for ever (see `register_handler`).

    With the default settings this is exactly JOB_STALL_SECONDS. The margin is
    deliberately the small one that keeps it there. A handler is cut before its
    AI deadline only if reading its files took longer than the margin *and* the
    AI call then ran to its own deadline, which is a failed job either way; the
    difference is only whether the handler or the worker ends it.

    UNMEASURED, like the AI deadline under it: no real job has been timed."""
    override = _timeouts.get(job_type)
    return override if override is not None else default_job_timeout_seconds()


def default_job_timeout_seconds() -> float:
    """The time limit of a job with no limit of its own, and the single number
    for "this job has run too long". Three places read it and must agree: the
    worker stops a job at it, /health/ready calls a job `stalled` past it, and
    `services/extraction.py:read_in_progress` stops believing a read is live
    past it. If they disagreed, a deployment that raised the AI deadline would
    have health calling a healthy job hung, and a tutor's fix queued beside a
    read that was still running."""
    return max(
        JOB_STALL_SECONDS,
        get_settings().ai_call_timeout_seconds + JOB_TIMEOUT_MARGIN_SECONDS,
    )


def is_permanent(exc: BaseException) -> bool:
    """Whether a second attempt at the job that raised `exc` cannot succeed.

    A failure opts out of the retry by carrying `job_retryable = False`, on
    the class or the instance. An attribute rather than a base class because
    some failures decide per instance (a provider error is permanent or not by
    its status). Named for this queue rather than plain `retryable` because
    other libraries use that word for their own purposes: google-auth's
    exceptions carry a `retryable` that defaults to False, and reading it here
    would have silently taken the retry away from them. The failures that set
    it are defined in `services/`: a missing API key, an answer cut off at the
    output limit, a request the provider rejected, an uploaded file that is
    gone. Everything unmarked keeps the retry: an unknown failure is treated as
    one that might pass, which is what the retry has always been for."""
    return getattr(exc, "job_retryable", True) is False


def _timeout_message(limit: float) -> str:
    return f"The job ran past its {limit:g}-second time limit and was stopped"


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
    - `stalled` — a single job has been in flight past the default time limit
      (`default_job_timeout_seconds`, JOB_STALL_SECONDS unless the AI deadline
      was raised). The worker stops a job there, so this state now means a job
      with a longer limit of its own (the booklet reader), a stop that is itself
      stuck, or the few seconds a normal stop takes to unwind and be recorded.
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
        state = "stalled" if job_seconds > default_job_timeout_seconds() else "running"
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
    # Reported as `unknown`, never as healthy.
    except Exception:  # noqa: BLE001
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


async def _tell_handler_it_was_given_up(job_type: str, payload: dict, error: str) -> None:
    """Run the job type's `on_give_up` hook, if it has one, after a job of that
    type ended `failed`. Never fatal: the job's own outcome is already
    committed, and a worker that cannot record this is still a worker that can
    do work. A cancellation of the worker passes straight through."""
    hook = _give_ups.get(job_type)
    if hook is None:
        return
    try:
        async with asyncio.timeout(GIVE_UP_TIMEOUT_SECONDS), async_session() as session:
            await hook(session, payload, error)
            await session.commit()
    except Exception:  # noqa: BLE001 — recording a failure must not stop the worker
        log.exception("could not record that a %s job was given up on", job_type)


async def _run_handler(job_id: int, job_type: str, payload: dict) -> tuple[str | None, bool]:
    """Run one claimed job's handler inside its time limit. Returns the error to
    record (None when the handler finished) and whether that failure itself
    says a second attempt cannot succeed. Never raises for a job's own failure;
    a cancellation of the worker passes straight through."""
    handler = _handlers.get(job_type)
    if handler is None:
        # Not permanent: during a deploy an older worker can claim a job type
        # only the newer code knows, and the retry lands on that.
        return f"No handler registered for job type '{job_type}'", False
    limit = job_timeout_seconds(job_type)
    try:
        # The session is opened inside the limit, so its rollback and close run
        # as the cancellation unwinds. `asyncio.timeout` turns only its own
        # cancellation into TimeoutError: a worker being shut down still sees
        # CancelledError and stops.
        async with asyncio.timeout(limit) as deadline, async_session() as session:
            await handler(session, payload)
            await session.commit()
    except Exception as exc:  # noqa: BLE001 — worker must survive any job error
        if isinstance(exc, TimeoutError) and deadline.expired():
            # Not marked permanent: a stall can be a one-off, and the retry is
            # the only second chance the work gets.
            log.error("job %s (%s) stopped at its %ss limit", job_id, job_type, limit)
            return _timeout_message(limit), False
        log.exception("job %s (%s) failed: %s", job_id, job_type, exc)
        return str(exc) or exc.__class__.__name__, is_permanent(exc)
    return None, False


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
        # Who holds this row, and since when (task 1.5, AV-84). Without it a
        # process killed mid-job leaves `running` with nothing naming the worker
        # that owed an answer, and no path anywhere reconsiders it.
        job.claimed_by = WORKER_ID
        job.claimed_at = datetime.now(timezone.utc)
        await session.commit()
        job_id, job_type, payload, attempts = job.id, job.type, job.payload, job.attempts

    await _write_heartbeat(job_started_at=datetime.now(timezone.utc))
    try:
        error, permanent = await _run_handler(job_id, job_type, payload)
        gave_up = False

        async with async_session() as session:
            job = await session.get(Job, job_id)
            assert job is not None
            # Cleared on every outcome below, including the retry: a pending row
            # is held by nobody, and a stale claimant on one would make the
            # orphan sweep reason about a worker that already let go.
            job.claimed_by = None
            job.claimed_at = None
            if error is None:
                job.status = JobStatus.done
                job.error = None
            elif attempts < MAX_ATTEMPTS and not permanent:
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
                gave_up = True
                # Nothing watches the failed count yet, so this line is the only
                # record that a piece of a student's work stopped moving.
                log.error(
                    "job %s (%s) gave up after %s attempt(s)%s: %s",
                    job_id,
                    job_type,
                    attempts,
                    ", a retry could not have helped" if permanent else "",
                    error,
                )
            await session.commit()
        # After the commit, never inside it: the job's own outcome is the
        # record that matters, and it must not wait on, or roll back with, a
        # write to some other row.
        if gave_up:
            assert error is not None
            await _tell_handler_it_was_given_up(job_type, payload, error)
    finally:
        await _write_heartbeat(job_started_at=None)
    return True


async def _sweep_orphans_safely() -> None:
    """`reclaim_orphaned_jobs`, but never fatal to the loop.

    Same posture as `_write_heartbeat`: a worker that cannot run the repair is
    still a worker that can do work, and a database blip must not take down job
    processing to perform maintenance on it.
    """
    try:
        await reclaim_orphaned_jobs()
    except Exception:  # noqa: BLE001 — a repair pass must not stop the worker
        log.exception("orphan sweep failed")


async def reclaim_orphaned_jobs(now: datetime | None = None) -> int:
    """Return jobs whose claiming worker is gone to `pending`. Returns how many.

    The queue's one unrecoverable state, until task 1.5 (AV-84). `running` is
    the status no retry path looks at: a worker killed mid-job left its row
    there permanently, the work stopped, and the only trace was a number on
    /health/ready that nothing watches.

    **The predicate is "the claimant has no heartbeat row", not "its heartbeat
    is stale".** That distinction is the difference between a repair and a
    duplicate-execution bug. `last_loop_at` is stamped by `worker_loop` *before*
    each claim, so a worker part-way through a slow marking call has a
    deliberately stale loop clock — it is healthy and working. Requeueing on
    staleness would hand its job to a second worker while the first still had
    it. A missing row means the process is gone: a live worker always has one
    and re-registers if its row is reaped (see `_write_heartbeat`).

    `ORPHAN_RECLAIM_SECONDS` guards the one case where a live worker can be
    row-less — a job in flight past the reap window — by waiting twice that
    window before believing it.

    Requeueing means a handler may run a second time on the same payload, which
    is safe only because `BE-6` requires exactly that. The alternative is a job
    that never finishes, so the idempotency requirement is what buys the repair.

    Attempts are not incremented here: the claim already did that, so a row
    orphaned at its last attempt fails rather than looping back into `running`
    forever.
    """
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=ORPHAN_RECLAIM_SECONDS)
    reclaimed = 0
    given_up: list[tuple[str, dict]] = []
    async with async_session() as session:
        orphans = (
            await session.scalars(
                select(Job)
                .where(
                    Job.status == JobStatus.running,
                    Job.claimed_at.is_not(None),
                    Job.claimed_at < cutoff,
                )
                # SKIP LOCKED for the same reason the claim query uses it: two
                # workers may sweep at once, and neither should wait on the
                # other to repair rows the loser would then re-examine.
                .with_for_update(skip_locked=True)
            )
        ).all()
        if not orphans:
            return 0

        live = set(
            (
                await session.scalars(
                    select(WorkerHeartbeat.worker_id).where(
                        WorkerHeartbeat.worker_id.in_(
                            {o.claimed_by for o in orphans if o.claimed_by}
                        )
                    )
                )
            ).all()
        )
        for job in orphans:
            if job.claimed_by is None or job.claimed_by in live:
                continue
            note = f"worker {job.claimed_by} disappeared while holding this job"
            if job.attempts < MAX_ATTEMPTS:
                job.status = JobStatus.pending
                job.error = note
            else:
                # Out of attempts. Failing is the honest end: another run would
                # be the third attempt on a job whose two claims both died, and
                # a row that cycles running -> pending -> running forever is the
                # stuck state this function exists to end, wearing a new hat.
                job.status = JobStatus.failed
                job.error = f"{note}; no attempts left"
                log.error("job %s (%s) orphaned with no attempts left", job.id, job.type)
                given_up.append((job.type, job.payload))
            job.claimed_by = None
            job.claimed_at = None
            reclaimed += 1
        await session.commit()

    # The worker's id means nothing to a tutor, so the row is given the plain
    # version of what happened rather than the job's own error.
    for job_type, payload in given_up:
        await _tell_handler_it_was_given_up(job_type, payload, ORPHANED_MESSAGE)

    if reclaimed:
        # ERROR, not INFO: reaching here means a worker died holding work.
        # The repair worked, and the death is still the thing to look at.
        log.error("requeued %s job(s) orphaned by a worker that disappeared", reclaimed)
    return reclaimed


async def worker_loop() -> None:
    global _last_heartbeat_write, _last_orphan_sweep
    await register_worker()
    log.info("job worker started (worker_id=%s)", WORKER_ID)
    # Immediately after registering, because that call is what reaps the dead
    # worker rows this sweep reads the absence of. A process that crashed
    # holding a job is therefore repaired by its own restart, which is the
    # common case and the one worth healing without waiting out an interval.
    #
    # Stamping the throttle is part of the call, not bookkeeping after it: the
    # loop below treats `None` as "never swept" and would run a second,
    # identical pass on its first iteration. Harmless but pointless — a full
    # scan of `running` rows on every worker boot to re-answer a question just
    # answered.
    await _sweep_orphans_safely()
    _last_orphan_sweep = datetime.now(timezone.utc)
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
        if (
            _last_orphan_sweep is None
            or (now - _last_orphan_sweep).total_seconds() >= ORPHAN_SWEEP_INTERVAL_SECONDS
        ):
            await _sweep_orphans_safely()
            _last_orphan_sweep = now
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
