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
from sqlalchemy import delete, select

from app.db import async_session
from app.models import Job, JobStatus, WorkerHeartbeat
from app.workers import jobs
from app.workers.jobs import (
    JOB_STALL_SECONDS,
    RETRY_BACKOFF_SECONDS,
    STALE_AFTER_SECONDS,
    enqueue,
    process_one_job,
    register_worker,
)
from app.workers.runner import supervised_worker


@pytest.fixture(autouse=True)
def _ai_configured(monkeypatch):
    """A deployment with its AI key set, which is what these tests are about.
    The suite itself has none (`QA-8`), and /health/ready reports a missing
    key as a failure; the tests that are about that set it back."""
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "anthropic_api_key", "configured-for-the-test")


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
    assert body["database"] == {"ok": True, "pool": None}
    assert body["queue"] == {
        "pending": 0,
        "running": 0,
        "failed": 0,
        "failed_queued_last_24h": 0,
        "oldest_pending_age_seconds": None,
        "oldest_due_age_seconds": None,
    }
    assert body["ai"] == {"ok": True, "missing_keys": []}
    assert body["auth"] == {"secret_ok": True}


async def test_readiness_counts_queued_work_and_its_age(client):
    async with async_session() as session:
        await enqueue(session, "compute_readiness_v2", {"student_id": 1})
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
    assert body["database"] == {"ok": True, "pool": None}


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
    assert body["database"] == {"ok": False, "error": "OSError", "pool": None}
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
        assert job.error == "Something went wrong on our side. Try again in a few minutes."
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
    assert body["database"] == {"ok": False, "error": "TimeoutError", "pool": None}
    # Not a queue of zeroes: PROD-2 applies to the platform's own telemetry.
    assert body["queue"] is None


# --- A reaped worker comes back ---------------------------------------------


async def test_a_worker_whose_row_was_reaped_re_registers():
    """A live worker must never be left working while invisible.

    register_worker() reaps a mid-job row once the job itself is older than
    HEARTBEAT_REAP_SECONDS, because a job in flight that long cannot be told
    apart from a process that died holding one. That is the right call, but it
    can hit a worker that is genuinely alive — another worker starting is
    enough. Before this, _write_heartbeat() found no row and returned silently
    while _worker_registered stayed True, so the loop never re-registered: the
    process went on doing work that no health answer could see, which is
    exactly the RISK-4 blindness this table exists to end.
    """
    await register_worker()
    assert jobs._worker_registered

    # Stand in for another worker's register_worker() reaping this one.
    async with async_session() as session:
        await session.execute(
            delete(WorkerHeartbeat).where(WorkerHeartbeat.worker_id == jobs.WORKER_ID)
        )
        await session.commit()

    # The write process_one_job() does in its finally when the job ends.
    await jobs._write_heartbeat(job_started_at=None)
    assert not jobs._worker_registered, "a vanished row must clear the flag, not pass silently"

    # worker_loop()'s existing retry, which the cleared flag hands it to.
    if not jobs._worker_registered:
        await register_worker()

    async with async_session() as session:
        row = await session.scalar(
            select(WorkerHeartbeat).where(WorkerHeartbeat.worker_id == jobs.WORKER_ID)
        )
    assert row is not None, "the worker must be visible again"
    assert jobs._worker_registered


# --- What /health/ready also sees (cleanup stage, OPS-05) -------------------


async def test_a_missing_ai_key_reports_503_and_names_the_provider(client, monkeypatch):
    """15 of the 18 failed jobs found in production were a missing key, each
    noticed only as one more failure. The key is now part of the answer."""
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "anthropic_api_key", "")

    resp = await client.get("/api/v1/health/ready")
    assert resp.status_code == 503
    assert resp.json()["ai"] == {"ok": False, "missing_keys": ["anthropic"]}


async def test_a_blank_ai_key_is_a_missing_one(client, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "anthropic_api_key", "   ")

    assert (await client.get("/api/v1/health/ready")).status_code == 503


async def test_a_misspelt_ai_provider_reports_503_without_echoing_the_setting(
    client, monkeypatch, caplog
):
    """The endpoint is public, and it logs on every poll. The setting's raw
    value, which someone could have pasted a key into by mistake, goes to
    neither."""
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "ai_marking_provider", "anthropik")

    resp = await client.get("/api/v1/health/ready")
    assert resp.status_code == 503
    assert resp.json()["ai"] == {"ok": False, "error": "provider_misconfigured"}
    assert "anthropik" not in resp.text
    assert any("AI_*_PROVIDER" in r.getMessage() for r in caplog.records)
    assert not any("anthropik" in r.getMessage() or r.exc_info for r in caplog.records)


async def _job(*, status: JobStatus, created_ago: float, run_after_in: float | None = None):
    now = datetime.now(timezone.utc)
    async with async_session() as session:
        session.add(
            Job(
                type="health_probe",
                payload={},
                status=status,
                created_at=now - timedelta(seconds=created_ago),
                run_after=None if run_after_in is None else now + timedelta(seconds=run_after_in),
            )
        )
        await session.commit()


async def test_a_long_backlog_is_reported_not_judged(client):
    """One tutor's batch of uploads can keep work waiting for half an hour while
    the worker drains it steadily. That is a backlog, not an outage; a queue
    that is not moving already shows as a stale or stalled worker."""
    await _job(status=JobStatus.pending, created_ago=3600)

    resp = await client.get("/api/v1/health/ready")
    assert resp.status_code == 200
    assert resp.json()["queue"]["oldest_due_age_seconds"] > 3500


async def test_work_scheduled_for_later_is_not_counted_as_waiting(client):
    """The weekly sweeps sit queued for up to a day by design. Judged by when it
    was queued, a healthy system would page every night."""
    await _job(status=JobStatus.pending, created_ago=86_000, run_after_in=3600)

    resp = await client.get("/api/v1/health/ready")
    assert resp.status_code == 200
    body = resp.json()["queue"]
    assert body["oldest_pending_age_seconds"] > 80_000
    assert body["oldest_due_age_seconds"] is None


async def test_due_age_counts_from_when_the_work_became_due(client):
    """A retry that waited out its backoff is due from its `run_after`, not from
    when it was first queued."""
    await _job(status=JobStatus.pending, created_ago=86_000, run_after_in=-30)

    body = (await client.get("/api/v1/health/ready")).json()["queue"]
    assert 0 < body["oldest_due_age_seconds"] < 120


async def test_recent_failures_are_counted_but_do_not_fail_the_check(client):
    """One unreadable upload fails for good and is not an outage."""
    await _job(status=JobStatus.failed, created_ago=60)
    await _job(status=JobStatus.failed, created_ago=2 * 86_400)

    resp = await client.get("/api/v1/health/ready")
    assert resp.status_code == 200
    assert resp.json()["queue"]["failed"] == 2
    assert resp.json()["queue"]["failed_queued_last_24h"] == 1


@pytest.fixture
def serving_since():
    """Stand in for a real deployment, whose lifespan stamps this."""
    from app.main import app

    def _set(seconds_ago: float):
        app.state.serving_since = datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)

    yield _set
    if hasattr(app.state, "serving_since"):
        del app.state.serving_since


async def test_a_deployment_with_no_worker_reports_503(client, serving_since):
    """The silent stop: the API serving happily, no background work running."""
    from app.main import WORKER_START_GRACE_SECONDS

    serving_since(WORKER_START_GRACE_SECONDS + 30)

    resp = await client.get("/api/v1/health/ready")
    assert resp.status_code == 503
    assert resp.json()["worker"]["state"] == "not_started"


async def test_a_deployment_still_starting_its_worker_is_not_failing(client, serving_since):
    serving_since(5)

    assert (await client.get("/api/v1/health/ready")).status_code == 200


@pytest.mark.parametrize(
    "secret",
    ["change-me-in-production", "  change-me-in-production  ", "short-secret", "x" * 31],
)
async def test_a_placeholder_or_short_sign_in_secret_reports_503_without_the_value(
    client, monkeypatch, secret
):
    """With the public placeholder anyone can sign a token for any account
    (`SA-04`). Reported as a yes or no: the answer is public, so it never
    carries the secret."""
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "jwt_secret", secret)

    resp = await client.get("/api/v1/health/ready")
    assert resp.status_code == 503
    assert resp.json()["auth"] == {"secret_ok": False}
    assert secret.strip() not in resp.text


@pytest.mark.parametrize("secret", ["x" * 32, "é" * 16])
async def test_a_32_byte_sign_in_secret_is_enough(client, monkeypatch, secret):
    """Bytes, not characters, as HS256 reads it: 16 accented letters are 32."""
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "jwt_secret", secret)

    resp = await client.get("/api/v1/health/ready")
    assert resp.status_code == 200, resp.text
    assert resp.json()["auth"] == {"secret_ok": True}
