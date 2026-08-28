"""RISK-4: a dead job worker used to be completely invisible.

The API kept serving, /health kept returning a hardcoded "ok", and every piece
of background work — extraction, marking, readiness synthesis, reports,
Classroom sync — had silently stopped. These tests pin the two halves of the
fix: liveness stays shallow so the platform can restart on it safely, and
readiness tells the truth about the worker and the queue.
"""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.db import async_session
from app.models import Job, JobStatus, WorkerHeartbeat
from app.workers import jobs
from app.workers.jobs import (
    JOB_STALL_SECONDS,
    RETRY_BACKOFF_SECONDS,
    STALE_AFTER_SECONDS,
    enqueue,
    process_one_job,
)
from app.workers.runner import supervised_worker


@pytest.fixture(autouse=True)
def _isolated_worker_state():
    """Reset the worker module's process-local flags around every test.

    Since task 1.3 the liveness clocks themselves live in the database (the
    `worker_heartbeats` table, reset per test by conftest's `_db_schema`), so
    what is left here is the two flags that stay in memory: whether this
    process has registered a worker, and when it last wrote its clock. A
    supervisor test that registers a worker would otherwise leave the flag set
    and let a later test write heartbeats it never asked for.
    """
    saved = (jobs._worker_registered, jobs._last_heartbeat_write)
    jobs._worker_registered = False
    jobs._last_heartbeat_write = None
    yield
    jobs._worker_registered, jobs._last_heartbeat_write = saved


async def _heartbeat(
    *,
    started_at: datetime | None = None,
    last_loop_at: datetime | None = None,
    job_started_at: datetime | None = None,
    restarts: list[str] | None = None,
    worker_id: str = "test-worker",
) -> None:
    """Insert a worker heartbeat row, standing in for a running worker.

    The tests below used to monkeypatch module globals. Now that the readiness
    endpoint reads the database, writing a row is both closer to what actually
    happens and a real exercise of the read path rather than a stand-in for it.
    """
    now = datetime.now(timezone.utc)
    async with async_session() as session:
        session.add(
            WorkerHeartbeat(
                worker_id=worker_id,
                started_at=started_at or now,
                last_loop_at=last_loop_at or now,
                job_started_at=job_started_at,
                restarts=restarts or [],
            )
        )
        await session.commit()


def _ago(seconds: float) -> datetime:
    return datetime.now(timezone.utc) - timedelta(seconds=seconds)


# --- Liveness --------------------------------------------------------------


async def test_liveness_stays_shallow_and_unchanged(client):
    """render.yaml points healthCheckPath here, and Render restarts an instance
    that fails it. It must not depend on the database or the worker, or a blip
    in either becomes a restart loop."""
    resp = await client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


# --- Readiness -------------------------------------------------------------


async def test_readiness_reports_the_database_and_the_queue(client):
    resp = await client.get("/api/v1/health/ready")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["database"] == {"ok": True}
    assert body["queue"] == {
        "pending": 0,
        "running": 0,
        "failed": 0,
        "oldest_pending_age_seconds": None,
    }


async def test_readiness_counts_queued_work_and_its_age(client):
    async with async_session() as session:
        await enqueue(session, "recompute_readiness", {"student_id": 1})
        await session.commit()

    body = (await client.get("/api/v1/health/ready")).json()
    assert body["queue"]["pending"] == 1
    assert body["queue"]["oldest_pending_age_seconds"] >= 0


async def test_a_worker_that_never_started_is_not_a_failure(client):
    """The test client never enters the app's lifespan, so the worker genuinely
    is not running. That is a test harness, not a broken deployment, and it must
    not report as one — otherwise the signal is noise everywhere it is read."""
    body = (await client.get("/api/v1/health/ready")).json()
    assert body["worker"]["state"] == "not_started"
    assert body["status"] == "ok"


async def test_a_worker_whose_loop_stopped_turning_reports_503(client):
    await _heartbeat(started_at=_ago(3600), last_loop_at=_ago(STALE_AFTER_SECONDS + 60))

    resp = await client.get("/api/v1/health/ready")
    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["worker"]["state"] == "stale"
    # The database is fine; only the worker is not. The body has to say which,
    # or the operator learns nothing the status code did not already tell them.
    assert body["database"] == {"ok": True}


async def test_a_worker_inside_a_slow_job_is_healthy(client):
    """A marking run holding the loop for a minute is working, not dead. Judging
    liveness on a single "last seen" clock would page on every slow AI call."""
    await _heartbeat(
        started_at=_ago(3600),
        last_loop_at=_ago(STALE_AFTER_SECONDS + 60),
        job_started_at=_ago(90),
    )

    resp = await client.get("/api/v1/health/ready")
    assert resp.status_code == 200
    assert resp.json()["worker"]["state"] == "running"


async def test_a_job_stuck_for_a_quarter_of_an_hour_reports_503(client):
    """The other half of the same judgement: a job that has not moved in fifteen
    minutes is hung, and it blocks every job behind it."""
    await _heartbeat(
        started_at=_ago(3600),
        last_loop_at=_ago(10),
        job_started_at=_ago(JOB_STALL_SECONDS + 60),
    )

    resp = await client.get("/api/v1/health/ready")
    assert resp.status_code == 503
    body = resp.json()
    assert body["worker"]["state"] == "stalled"
    assert body["worker"]["job_running_seconds"] > JOB_STALL_SECONDS


async def test_an_unreachable_database_reports_503_without_raising(client, monkeypatch):
    def _refused():
        raise OSError("connection refused")

    monkeypatch.setattr("app.main.async_session", _refused)

    resp = await client.get("/api/v1/health/ready")
    assert resp.status_code == 503
    body = resp.json()
    assert body["database"] == {"ok": False, "error": "OSError"}
    # Nothing is known about the queue when the database is gone. Reporting
    # zeroes here would be inventing a measurement (PROD-2).
    assert body["queue"] is None


# --- Supervision -----------------------------------------------------------


async def _run_supervisor_until(
    restarted: asyncio.Event,
    timeout: float = 5.0,  # noqa: ASYNC109 — reasoned in the docstring
) -> None:
    """Run the supervisor until it has restarted the worker, then stop it.

    Waits on an event rather than sleeping a fixed interval: a wall-clock sleep
    makes the assertion depend on how loaded the CI runner is, and it fails as a
    confusing count comparison rather than as "the restart never happened".

    ASYNC109 would have the caller wrap this in `asyncio.timeout` instead of the
    helper taking the argument. That rule is aimed at library APIs, where the
    caller owns the deadline. Here the deadline is a property of the helper —
    every call site wants the same "it should have restarted by now" bound — and
    pushing it outward would repeat it at each one.
    """
    task = asyncio.create_task(supervised_worker())
    try:
        await asyncio.wait_for(restarted.wait(), timeout=timeout)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


async def test_a_worker_that_raises_is_restarted(monkeypatch):
    """The failure this exists for: lifespan created the task and never looked
    at it again, so an exception escaping worker_loop() ended background work
    for the life of the process while the API carried on serving."""
    calls = {"n": 0}
    restarted = asyncio.Event()

    async def _dies():
        calls["n"] += 1
        if calls["n"] > 1:
            restarted.set()
        raise RuntimeError("worker died")

    monkeypatch.setattr("app.workers.runner.worker_loop", _dies)
    monkeypatch.setattr("app.workers.runner.WORKER_RESTART_SECONDS", 0.01)

    await _run_supervisor_until(restarted)
    assert calls["n"] > 1, "a dead worker must be restarted, not merely logged"


async def test_a_worker_that_returns_cleanly_is_also_restarted(monkeypatch):
    """worker_loop() loops forever, so returning at all is a bug — and one that
    stops the queue just as completely as an exception does."""
    calls = {"n": 0}
    restarted = asyncio.Event()

    async def _returns():
        calls["n"] += 1
        if calls["n"] > 1:
            restarted.set()

    monkeypatch.setattr("app.workers.runner.worker_loop", _returns)
    monkeypatch.setattr("app.workers.runner.WORKER_RESTART_SECONDS", 0.01)

    await _run_supervisor_until(restarted)
    assert calls["n"] > 1


async def test_shutdown_still_stops_the_worker(monkeypatch):
    """Supervision must not defeat lifespan's cancellation, or every deploy
    would hang waiting for a worker that keeps restarting itself."""
    started = asyncio.Event()

    async def _runs_forever():
        started.set()
        await asyncio.sleep(3600)

    monkeypatch.setattr("app.workers.runner.worker_loop", _runs_forever)

    task = asyncio.create_task(supervised_worker())
    await asyncio.wait_for(started.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert task.cancelled()


# --- Retry backoff ---------------------------------------------------------


async def test_a_failed_job_waits_before_its_second_attempt(client, monkeypatch):
    """Retries existed but were pointless: a failed job went straight back to
    pending and was re-claimed on the next ~2s poll, so both attempts were spent
    inside a few seconds — no use at all against the rate limits and timeouts
    that retrying is for."""

    async def _always_fails(session, payload):
        raise RuntimeError("provider rate limited")

    monkeypatch.setitem(
        __import__("app.workers.jobs", fromlist=["_handlers"])._handlers,
        "test_failing",
        _always_fails,
    )

    async with async_session() as session:
        await enqueue(session, "test_failing", {})
        await session.commit()

    assert await process_one_job() is True

    async with async_session() as session:
        job = await session.scalar(select(Job))
        assert job.status == JobStatus.pending, "first failure must schedule a retry"
        assert job.error == "provider rate limited"
        assert job.run_after is not None, "the retry must be held back, not immediately due"
        run_after = job.run_after
        if run_after.tzinfo is None:
            run_after = run_after.replace(tzinfo=timezone.utc)
        waiting = (run_after - datetime.now(timezone.utc)).total_seconds()
        assert 0 < waiting <= RETRY_BACKOFF_SECONDS

    # And it is genuinely not claimable yet, rather than merely marked.
    assert await process_one_job() is False


async def test_a_job_that_fails_twice_is_marked_failed(client, monkeypatch):
    async def _always_fails(session, payload):
        raise RuntimeError("still broken")

    monkeypatch.setitem(
        __import__("app.workers.jobs", fromlist=["_handlers"])._handlers,
        "test_failing",
        _always_fails,
    )

    async with async_session() as session:
        await enqueue(session, "test_failing", {})
        await session.commit()

    assert await process_one_job() is True
    async with async_session() as session:
        job = await session.scalar(select(Job))
        job.run_after = None  # skip the backoff rather than sleep through it
        await session.commit()
    assert await process_one_job() is True

    async with async_session() as session:
        job = await session.scalar(select(Job))
        assert job.status == JobStatus.failed
        assert job.attempts == 2

    # A failed job is exactly what readiness has to surface — nothing else does.
    body = (await client.get("/api/v1/health/ready")).json()
    assert body["queue"]["failed"] == 1


# --- Crash looping ----------------------------------------------------------


async def test_a_crash_looping_worker_is_not_reported_healthy(client):
    """The hole the supervisor opened while closing another one.

    worker_loop() re-stamps its liveness clock on entry, so a loop that raises
    immediately and is restarted every few seconds keeps a fresh timestamp. On
    the two original clocks that is indistinguishable from a healthy worker —
    readiness would answer 200 while no job ever completed, which is precisely
    the condition the endpoint exists to expose.
    """
    now = datetime.now(timezone.utc)
    await _heartbeat(
        started_at=now - timedelta(seconds=60),
        last_loop_at=now,  # fresh, as a crash loop keeps it
        job_started_at=None,
        restarts=[(now - timedelta(seconds=s)).isoformat() for s in (30, 20, 10)],
    )

    status_ = await jobs.worker_status()
    assert status_.state == "crash_looping"
    assert status_.healthy is False

    resp = await client.get("/api/v1/health/ready")
    assert resp.status_code == 503
    body = resp.json()
    assert body["worker"]["state"] == "crash_looping"
    assert body["worker"]["restarts_in_window"] == 3
    assert body["worker"]["last_restart_at"] is not None


async def test_one_restart_is_the_supervisor_working_not_a_crash_loop():
    """A single restart is the supervisor doing its job. Reporting that as a
    failure would make the fix for RISK-4 page on its own success."""
    now = datetime.now(timezone.utc)
    await _heartbeat(started_at=now, last_loop_at=now, restarts=[now.isoformat()])
    status_ = await jobs.worker_status(now)
    assert status_.restarts_in_window == 1
    assert status_.healthy is True


async def test_restarts_age_out_of_the_window():
    """A worker that restarted three times last week is not crash looping now."""
    now = datetime.now(timezone.utc)
    stale = (now - timedelta(seconds=jobs.CRASH_LOOP_WINDOW_SECONDS + 60)).isoformat()
    await _heartbeat(
        started_at=now - timedelta(seconds=60),
        last_loop_at=now,
        restarts=[stale, stale, stale],
    )

    status_ = await jobs.worker_status(now)
    assert status_.restarts_in_window == 0
    assert status_.state == "running"


async def test_the_supervisor_records_each_restart(monkeypatch):
    """The counter is only useful if the supervisor actually feeds it."""
    # The supervisor only records a restart for a registered worker, which is
    # what a real one is by the time it can be restarted at all.
    await _heartbeat(worker_id=jobs.WORKER_ID)
    monkeypatch.setattr(jobs, "_worker_registered", True)
    restarted = asyncio.Event()
    calls = {"n": 0}

    async def _dies():
        calls["n"] += 1
        if calls["n"] > 1:
            restarted.set()
        raise RuntimeError("worker died")

    monkeypatch.setattr("app.workers.runner.worker_loop", _dies)
    monkeypatch.setattr("app.workers.runner.WORKER_RESTART_SECONDS", 0.01)

    await _run_supervisor_until(restarted)
    status_ = await jobs.worker_status()
    assert status_.restarts_in_window >= 1, "the supervisor must record its restarts"


# --- Readiness does not hang ------------------------------------------------


async def test_a_hanging_database_is_reported_rather_than_waited_out(client, monkeypatch):
    """A refused connection raises promptly; an exhausted pool does not. Without
    a bound the probe would wait out pool_timeout (30s by default) and an
    external monitor would time out having learned nothing, where a 503 says
    exactly what is wrong."""

    async def _never_answers():
        await asyncio.sleep(60)

    monkeypatch.setattr("app.main._queue_snapshot", _never_answers)
    monkeypatch.setattr("app.main.READINESS_DB_TIMEOUT_SECONDS", 0.05)

    resp = await client.get("/api/v1/health/ready")

    assert resp.status_code == 503
    body = resp.json()
    assert body["database"] == {"ok": False, "error": "TimeoutError"}
    # Not a queue of zeroes: PROD-2 applies to the platform's own telemetry.
    assert body["queue"] is None
