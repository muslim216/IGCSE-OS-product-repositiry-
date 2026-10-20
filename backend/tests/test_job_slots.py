"""More than one job at a time in one worker (`CAP-2`): the extra slots leave
background work to the first, the heartbeat still sees a stuck job while others
come and go, and one slot (the default) is exactly the old single loop.

The loop itself is never run for real here (`QA-6`); its parts are."""

import asyncio

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.db import async_session
from app.models import Job, JobStatus, WorkerHeartbeat
from app.workers import jobs
from app.workers.jobs import enqueue, process_one_job, register_worker

BACKGROUND = "test_background_job"
WAITING = "test_waiting_job"


@pytest.fixture
def handlers(monkeypatch):
    ran: list[str] = []

    async def background(session, payload):
        ran.append(BACKGROUND)

    async def waiting(session, payload):
        ran.append(WAITING)

    monkeypatch.setitem(jobs._handlers, BACKGROUND, background)
    monkeypatch.setitem(jobs._handlers, WAITING, waiting)
    monkeypatch.setattr(jobs, "_background", {BACKGROUND})
    return ran


async def _queue(*job_types: str) -> None:
    async with async_session() as session:
        for job_type in job_types:
            await enqueue(session, job_type, {})
        await session.commit()


async def test_an_extra_slot_passes_over_background_work_to_the_next_waiting_job(handlers):
    await _queue(BACKGROUND, WAITING)  # the background job is older
    assert await process_one_job(skip_background=True) is True
    assert handlers == [WAITING]


async def test_an_extra_slot_with_only_background_work_queued_takes_nothing(handlers):
    await _queue(BACKGROUND)
    assert await process_one_job(skip_background=True) is False
    async with async_session() as session:
        assert (await session.scalar(select(Job.status))) == JobStatus.pending


async def test_the_first_slot_still_takes_everything_in_order(handlers):
    await _queue(BACKGROUND, WAITING)
    assert await process_one_job() is True
    assert await process_one_job() is True
    assert handlers == [BACKGROUND, WAITING]


async def _heartbeat_job_started_at():
    async with async_session() as session:
        return await session.scalar(
            select(WorkerHeartbeat.job_started_at).where(
                WorkerHeartbeat.worker_id == jobs.WORKER_ID
            )
        )


async def test_the_heartbeat_keeps_the_oldest_running_job_while_others_finish(monkeypatch):
    """A stuck job must still read as `stalled` after a quicker one beside it
    finishes; one shared "job started" clock would be cleared by that finish."""
    # Restored afterwards, so the registration does not leak into other tests.
    monkeypatch.setattr(jobs, "_worker_registered", False)
    monkeypatch.setattr(jobs, "_in_flight", {})
    await register_worker()
    first_started, second_started = asyncio.Event(), asyncio.Event()
    release_first, release_second = asyncio.Event(), asyncio.Event()

    async def first(session, payload):
        first_started.set()
        await release_first.wait()

    async def second(session, payload):
        second_started.set()
        await release_second.wait()

    monkeypatch.setitem(jobs._handlers, "test_first", first)
    monkeypatch.setitem(jobs._handlers, "test_second", second)
    await _queue("test_first")
    one = asyncio.create_task(process_one_job())
    await asyncio.wait_for(first_started.wait(), timeout=5)
    oldest = await _heartbeat_job_started_at()
    await _queue("test_second")
    two = asyncio.create_task(process_one_job())
    await asyncio.wait_for(second_started.wait(), timeout=5)

    release_second.set()
    await asyncio.wait_for(two, timeout=5)
    assert await _heartbeat_job_started_at() == oldest  # still the stuck one

    release_first.set()
    await asyncio.wait_for(one, timeout=5)
    assert await _heartbeat_job_started_at() is None


@pytest.mark.parametrize(("concurrency", "extra"), [(1, 0), (3, 2)])
async def test_the_loop_starts_one_extra_slot_per_extra_job(monkeypatch, concurrency, extra):
    """Run with the slots stubbed out: one slot (the default) is the old single
    loop alone; three add two slots that skip background work."""
    started: list[str] = []

    async def first_slot():
        started.append("first")
        await asyncio.sleep(0.05)
        raise asyncio.CancelledError

    async def extra_slot():
        started.append("extra")
        await asyncio.sleep(30)

    monkeypatch.setattr(get_settings(), "worker_concurrency", concurrency)
    monkeypatch.setattr(jobs, "_first_slot", first_slot)
    monkeypatch.setattr(jobs, "_extra_slot", extra_slot)
    with pytest.raises(asyncio.CancelledError):
        await jobs.worker_loop()
    assert started.count("first") == 1
    assert started.count("extra") == extra


async def test_an_extra_slot_claims_without_background_work(monkeypatch):
    asked: list[dict] = []

    async def claim(**kwargs):
        asked.append(kwargs)
        raise asyncio.CancelledError

    monkeypatch.setattr(jobs, "process_one_job", claim)
    with pytest.raises(asyncio.CancelledError):
        await jobs._extra_slot()
    assert asked == [{"skip_background": True}]


async def test_an_extra_slot_carries_on_after_an_error(monkeypatch):
    calls = 0

    async def claim(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("database blip")
        raise asyncio.CancelledError

    monkeypatch.setattr(jobs, "POLL_SECONDS", 0.01)
    monkeypatch.setattr(jobs, "process_one_job", claim)
    with pytest.raises(asyncio.CancelledError):
        await jobs._extra_slot()
    assert calls == 2


def test_only_work_nobody_waits_on_is_background():
    """A waiting type marked background by mistake would never run on an extra
    slot; this names the split."""
    from app.workers.handlers import register_all

    register_all()
    for waiting in (
        "mark_submission",
        "extract_assignment",
        "generate_report",
        "send_notification",
    ):
        assert waiting not in jobs._background
    for background in ("tag_mistakes", "compute_readiness_v2", "sweep_retention"):
        assert background in jobs._background


async def test_re_registering_keeps_a_running_job_on_show(monkeypatch):
    started = jobs.datetime.now(jobs.timezone.utc)
    monkeypatch.setattr(jobs, "_worker_registered", False)
    monkeypatch.setattr(jobs, "_in_flight", {7: started})
    await register_worker()
    assert await _heartbeat_job_started_at() is not None


async def test_a_finished_job_still_records_its_outcome_when_the_pool_is_briefly_full(
    monkeypatch,
):
    """The work is done; a full pool at the moment of writing it down must not
    leave the row `running` under a live worker, which nothing reclaims (`CAP-16`)."""
    from sqlalchemy.exc import TimeoutError as PoolTimeoutError

    async def done(session, payload):
        pass

    real = jobs._record_outcome
    tries = 0

    async def full_once(*args):
        nonlocal tries
        tries += 1
        if tries == 1:
            raise PoolTimeoutError("QueuePool limit reached")
        return await real(*args)

    monkeypatch.setitem(jobs._handlers, WAITING, done)
    monkeypatch.setattr(jobs, "POLL_SECONDS", 0.01)
    monkeypatch.setattr(jobs, "_record_outcome", full_once)
    await _queue(WAITING)
    assert await process_one_job() is True
    assert tries == 2
    async with async_session() as session:
        assert (await session.scalar(select(Job.status))) == JobStatus.done


async def test_a_job_turned_away_by_a_full_pool_is_retried_with_a_plain_reason(monkeypatch):
    from sqlalchemy.exc import TimeoutError as PoolTimeoutError

    async def busy(session, payload):
        raise PoolTimeoutError("QueuePool limit of size 10 overflow 10 reached")

    monkeypatch.setitem(jobs._handlers, WAITING, busy)
    await _queue(WAITING)
    assert await process_one_job() is True
    async with async_session() as session:
        job = await session.scalar(select(Job))
    assert job.status == JobStatus.pending
    assert job.error == "Avora was too busy to run this; it will be tried again"
