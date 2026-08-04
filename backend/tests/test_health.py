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
from app.main import _supervised_worker
from app.models import Job, JobStatus
from app.workers.jobs import (
    JOB_STALL_SECONDS,
    RETRY_BACKOFF_SECONDS,
    STALE_AFTER_SECONDS,
    enqueue,
    process_one_job,
)

STALE_MARKER = "app.workers.jobs._last_loop_at"
STARTED_MARKER = "app.workers.jobs._started_at"
IN_FLIGHT_MARKER = "app.workers.jobs._job_started_at"


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


async def test_a_worker_whose_loop_stopped_turning_reports_503(client, monkeypatch):
    monkeypatch.setattr(STARTED_MARKER, _ago(3600))
    monkeypatch.setattr(STALE_MARKER, _ago(STALE_AFTER_SECONDS + 60))

    resp = await client.get("/api/v1/health/ready")
    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["worker"]["state"] == "stale"
    # The database is fine; only the worker is not. The body has to say which,
    # or the operator learns nothing the status code did not already tell them.
    assert body["database"] == {"ok": True}


async def test_a_worker_inside_a_slow_job_is_healthy(client, monkeypatch):
    """A marking run holding the loop for a minute is working, not dead. Judging
    liveness on a single "last seen" clock would page on every slow AI call."""
    monkeypatch.setattr(STARTED_MARKER, _ago(3600))
    monkeypatch.setattr(STALE_MARKER, _ago(STALE_AFTER_SECONDS + 60))
    monkeypatch.setattr(IN_FLIGHT_MARKER, _ago(90))

    resp = await client.get("/api/v1/health/ready")
    assert resp.status_code == 200
    assert resp.json()["worker"]["state"] == "running"


async def test_a_job_stuck_for_a_quarter_of_an_hour_reports_503(client, monkeypatch):
    """The other half of the same judgement: a job that has not moved in fifteen
    minutes is hung, and it blocks every job behind it."""
    monkeypatch.setattr(STARTED_MARKER, _ago(3600))
    monkeypatch.setattr(STALE_MARKER, _ago(10))
    monkeypatch.setattr(IN_FLIGHT_MARKER, _ago(JOB_STALL_SECONDS + 60))

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


async def _run_supervisor_briefly(seconds: float = 0.2) -> None:
    task = asyncio.create_task(_supervised_worker())
    await asyncio.sleep(seconds)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_a_worker_that_raises_is_restarted(monkeypatch):
    """The failure this exists for: lifespan created the task and never looked
    at it again, so an exception escaping worker_loop() ended background work
    for the life of the process while the API carried on serving."""
    calls = {"n": 0}

    async def _dies():
        calls["n"] += 1
        raise RuntimeError("worker died")

    monkeypatch.setattr("app.main.worker_loop", _dies)
    monkeypatch.setattr("app.main.WORKER_RESTART_SECONDS", 0.01)

    await _run_supervisor_briefly()
    assert calls["n"] > 1, "a dead worker must be restarted, not merely logged"


async def test_a_worker_that_returns_cleanly_is_also_restarted(monkeypatch):
    """worker_loop() loops forever, so returning at all is a bug — and one that
    stops the queue just as completely as an exception does."""
    calls = {"n": 0}

    async def _returns():
        calls["n"] += 1

    monkeypatch.setattr("app.main.worker_loop", _returns)
    monkeypatch.setattr("app.main.WORKER_RESTART_SECONDS", 0.01)

    await _run_supervisor_briefly()
    assert calls["n"] > 1


async def test_shutdown_still_stops_the_worker(monkeypatch):
    """Supervision must not defeat lifespan's cancellation, or every deploy
    would hang waiting for a worker that keeps restarting itself."""
    started = asyncio.Event()

    async def _runs_forever():
        started.set()
        await asyncio.sleep(3600)

    monkeypatch.setattr("app.main.worker_loop", _runs_forever)

    task = asyncio.create_task(_supervised_worker())
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
