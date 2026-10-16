"""A job in flight when the server stops is not lost for hours.

Two ways a worker stops holding a job. Told to stop (a deploy, a restart, the
instance going to sleep): it hands the job back itself. Killed (a crash, the
memory limit): the orphan sweep finds the job once the worker has been silent
longer than any live worker can be, which the job time limits now bound.
Before both, either way left the job `running` until a restart at least three
hours later, with nobody told."""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.db import async_session
from app.models import Job, JobStatus, WorkerHeartbeat
from app.workers import jobs
from app.workers.handlers import register_all
from app.workers.jobs import (
    GIVE_UP_TIMEOUT_SECONDS,
    HANDED_BACK_MESSAGE,
    JOB_TIMEOUT_MARGIN_SECONDS,
    MAX_ATTEMPTS,
    ORPHAN_GRACE_SECONDS,
    enqueue,
    orphan_reclaim_seconds,
    process_one_job,
    reclaim_orphaned_jobs,
)

JOB = "restart_probe"


@pytest.fixture
def handler(monkeypatch):
    def _register(fn):
        monkeypatch.setitem(jobs._handlers, JOB, fn)
        monkeypatch.delitem(jobs._timeouts, JOB, raising=False)
        monkeypatch.delitem(jobs._give_ups, JOB, raising=False)

    return _register


async def _queue() -> None:
    async with async_session() as session:
        await enqueue(session, JOB, {"thing_id": 1})
        await session.commit()


async def _the_job() -> Job:
    async with async_session() as session:
        job = await session.scalar(select(Job).where(Job.type == JOB))
        assert job is not None
        return job


# --- Told to stop -----------------------------------------------------------


async def _stop_mid_job() -> None:
    started = asyncio.Event()

    async def _waits(session, payload):
        started.set()
        await asyncio.sleep(30)

    jobs._handlers[JOB] = _waits
    task = asyncio.create_task(process_one_job())
    await asyncio.wait_for(started.wait(), timeout=5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_a_job_stopped_at_shutdown_goes_straight_back_to_the_queue(client, handler):
    handler(None)
    await _queue()

    await _stop_mid_job()

    job = await _the_job()
    assert job.status == JobStatus.pending
    assert job.claimed_by is None
    assert job.claimed_at is None
    assert job.run_after is None, "due at once: nothing about the job asked for a wait"
    assert job.error == HANDED_BACK_MESSAGE


async def test_a_stop_at_shutdown_does_not_use_up_an_attempt(client, handler):
    """Two deploys during one long job must not fail it."""
    handler(None)
    await _queue()

    for _ in range(MAX_ATTEMPTS + 1):
        await _stop_mid_job()

    job = await _the_job()
    assert job.status == JobStatus.pending
    assert job.attempts == 0


async def test_the_next_worker_runs_a_handed_back_job(client, handler):
    handler(None)
    await _queue()
    await _stop_mid_job()

    ran: list[dict] = []

    async def _fine(session, payload):
        ran.append(payload)

    handler(_fine)
    assert await process_one_job() is True

    assert ran == [{"thing_id": 1}]
    job = await _the_job()
    assert job.status == JobStatus.done
    assert job.attempts == 1
    assert job.error is None


async def test_a_job_another_worker_now_holds_is_not_handed_back(client, handler):
    """Only this worker's own claim is given back. A row the sweep has already
    requeued and someone else claimed belongs to them."""
    handler(None)
    await _queue()
    async with async_session() as session:
        job = await session.scalar(select(Job).where(Job.type == JOB))
        job.status = JobStatus.running
        job.attempts = 1
        job.claimed_by = "someone-else"
        job.claimed_at = datetime.now(timezone.utc)
        await session.commit()
        job_id = job.id

    await jobs._hand_back(job_id)

    job = await _the_job()
    assert job.status == JobStatus.running
    assert job.claimed_by == "someone-else"
    assert job.attempts == 1


async def test_a_hand_back_that_cannot_reach_the_database_does_not_hold_shutdown(
    client, handler, monkeypatch, caplog
):
    def _no_database():
        raise ConnectionError("database is gone")

    monkeypatch.setattr(jobs, "async_session", _no_database)

    await asyncio.wait_for(jobs._hand_back(1), timeout=5)

    assert any("could not hand job 1 back" in r.getMessage() for r in caplog.records)


async def test_a_cancellation_from_inside_the_handler_is_a_failure_not_a_shutdown(client, handler):
    """Only a worker that was asked to stop hands its job back. A handler that
    cancels its own work is failing, keeps the attempt it used, and the worker
    carries on; refunding it would let such a job run for ever."""

    async def _cancels_itself(session, payload):
        raise asyncio.CancelledError

    handler(_cancels_itself)
    await _queue()

    assert await process_one_job() is True

    job = await _the_job()
    assert job.status == JobStatus.pending
    assert job.attempts == 1
    assert job.error == "The work was cancelled before it finished"


async def test_an_outcome_for_a_job_someone_else_now_holds_is_dropped(client, handler):
    """A worker stalled past the window can find, when it finally finishes,
    that the sweep requeued its job and another worker claimed it. The late
    outcome must not overwrite theirs."""

    async def _taken_over(session, payload):
        async with async_session() as other:
            job = await other.scalar(select(Job).where(Job.type == JOB))
            job.claimed_by = "the-worker-that-took-it"
            await other.commit()

    handler(_taken_over)
    await _queue()

    assert await process_one_job() is True

    job = await _the_job()
    assert job.status == JobStatus.running
    assert job.claimed_by == "the-worker-that-took-it"


# --- Killed -----------------------------------------------------------------


async def _held_by(worker_id: str, *, claimed_ago: float, attempts: int = 1) -> None:
    async with async_session() as session:
        session.add(
            Job(
                type=JOB,
                payload={"thing_id": 1},
                status=JobStatus.running,
                attempts=attempts,
                claimed_by=worker_id,
                claimed_at=datetime.now(timezone.utc) - timedelta(seconds=claimed_ago),
            )
        )
        await session.commit()


async def _heartbeat(worker_id: str, *, quiet_for: float) -> None:
    now = datetime.now(timezone.utc)
    async with async_session() as session:
        session.add(
            WorkerHeartbeat(
                worker_id=worker_id,
                started_at=now - timedelta(hours=1),
                last_loop_at=now - timedelta(seconds=quiet_for),
                job_started_at=now - timedelta(seconds=quiet_for),
                restarts=[],
            )
        )
        await session.commit()


async def test_a_crashed_workers_job_comes_back_once_its_claim_passes_the_window(client):
    """The case the old sweep could not see: the dead worker's heartbeat row is
    still there, because nothing reaps it for an hour, and the claim was under
    two hours old. It waited for a restart at least three hours later."""
    window = orphan_reclaim_seconds()
    await _heartbeat("crashed", quiet_for=window + 60)
    await _held_by("crashed", claimed_ago=window + 60)

    assert await reclaim_orphaned_jobs() == 1

    job = await _the_job()
    assert job.status == JobStatus.pending
    assert "crashed" in job.error


async def test_a_worker_still_inside_its_time_limit_keeps_its_job(client):
    """A slow job is not a dead worker: its loop clock is stale by design, and
    inside the window that means nothing."""
    window = orphan_reclaim_seconds()
    await _heartbeat("busy", quiet_for=window - 60)
    await _held_by("busy", claimed_ago=window - 60)

    assert await reclaim_orphaned_jobs() == 0
    assert (await _the_job()).status == JobStatus.running


async def test_a_claim_past_the_window_is_repaired_even_with_a_fresh_heartbeat(client):
    """A live worker whose outcome write failed leaves its row `running` and
    carries on looping. The old sweep counted any heartbeat row as alive, so
    that row stayed stuck for as long as the worker lived."""
    window = orphan_reclaim_seconds()
    await _heartbeat("alive-but-dropped-it", quiet_for=5)
    await _held_by("alive-but-dropped-it", claimed_ago=window + 60)

    assert await reclaim_orphaned_jobs() == 1
    assert (await _the_job()).status == JobStatus.pending


async def test_a_young_claim_is_left_even_when_its_worker_has_no_row(client):
    await _held_by("vanished", claimed_ago=60)

    assert await reclaim_orphaned_jobs() == 0


def test_the_window_covers_the_longest_job_and_comes_back_in_minutes(monkeypatch):
    """The safety argument, as numbers: no live claim outlasts the longest job
    limit plus the grace, so the window is that, and it is minutes rather than
    the hours it used to be."""
    monkeypatch.setattr(jobs, "_handlers", {})
    monkeypatch.setattr(jobs, "_timeouts", {})
    monkeypatch.setattr(jobs, "_give_ups", {})
    register_all()

    booklet = 2 * get_settings().ai_call_timeout_seconds + JOB_TIMEOUT_MARGIN_SECONDS
    assert max(jobs._timeouts.values()) == booklet
    assert orphan_reclaim_seconds() == booklet + GIVE_UP_TIMEOUT_SECONDS + ORPHAN_GRACE_SECONDS
    assert orphan_reclaim_seconds() <= 40 * 60


def test_raising_the_ai_deadline_widens_the_window(monkeypatch):
    monkeypatch.setattr(jobs, "_timeouts", {})
    before = orphan_reclaim_seconds()
    monkeypatch.setattr(get_settings(), "ai_call_timeout_seconds", 3000.0)
    assert orphan_reclaim_seconds() > before
