"""The job worker's two limits: how long one job may run, and when a failure is
not worth the retry.

Until these, a handler that never returned held the only worker for good, and
every failure was retried a minute later whether or not a minute could change
anything — a missing API key, an answer cut off at the output limit and a file
that is gone all fail identically the second time, and the AI ones are billed
twice for it."""

import asyncio

import pytest
from sqlalchemy import func, select

from app.db import async_session
from app.models import Job, JobStatus
from app.services import storage
from app.services.ai import (
    AICallFailedError,
    AIKeyMissingError,
    AIOutputTruncatedError,
    AITimeoutError,
    AIUnavailableError,
)
from app.workers import jobs
from app.workers.handlers import BOOKLET_READ_MARGIN_SECONDS, register_all
from app.workers.jobs import (
    JOB_STALL_SECONDS,
    JOB_TIMEOUT_SECONDS,
    enqueue,
    is_permanent,
    job_timeout_seconds,
    process_one_job,
    register_handler,
)

JOB = "limits_probe"


@pytest.fixture
def handler(monkeypatch):
    """Register a handler for JOB for one test, leaving no trace in the
    process-global registry (handlers and time limits both)."""

    def _register(fn, *, timeout_seconds=None):
        monkeypatch.setitem(jobs._handlers, JOB, fn)
        if timeout_seconds is not None:
            monkeypatch.setitem(jobs._timeouts, JOB, timeout_seconds)

    return _register


async def _queue() -> None:
    async with async_session() as session:
        await enqueue(session, JOB, {})
        await session.commit()


async def _the_job() -> Job:
    async with async_session() as session:
        job = await session.scalar(select(Job).where(Job.type == JOB))
        assert job is not None
        return job


async def _skip_backoff() -> None:
    async with async_session() as session:
        job = await session.scalar(select(Job).where(Job.type == JOB))
        job.run_after = None
        await session.commit()


# --- A time limit on every job ---------------------------------------------


def test_the_limit_is_where_a_job_is_already_called_hung():
    """One number, so the worker acts at the moment health starts reporting the
    job as stalled rather than some other moment."""
    assert JOB_TIMEOUT_SECONDS == JOB_STALL_SECONDS


async def test_a_handler_that_never_returns_is_stopped(client, handler, monkeypatch):
    monkeypatch.setattr(jobs, "JOB_TIMEOUT_SECONDS", 0.05)
    stopped = asyncio.Event()

    async def _hangs(session, payload):
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            stopped.set()
            raise

    handler(_hangs)
    await _queue()

    assert await asyncio.wait_for(process_one_job(), timeout=5) is True

    assert stopped.is_set(), "the handler itself must be cancelled, not just abandoned"
    job = await _the_job()
    assert job.status == JobStatus.pending, "a stall gets the one retry, like any failure"
    assert job.error == "The job ran past its 0.05-second time limit and was stopped"
    assert job.claimed_by is None and job.claimed_at is None


async def test_a_job_stopped_twice_is_failed_and_the_queue_moves_on(client, handler, monkeypatch):
    monkeypatch.setattr(jobs, "JOB_TIMEOUT_SECONDS", 0.05)

    async def _hangs(session, payload):
        await asyncio.sleep(30)

    handler(_hangs)
    await _queue()

    assert await asyncio.wait_for(process_one_job(), timeout=5) is True
    await _skip_backoff()
    assert await asyncio.wait_for(process_one_job(), timeout=5) is True

    job = await _the_job()
    assert job.status == JobStatus.failed
    assert job.attempts == 2
    assert "time limit" in job.error
    # The point of the limit: the worker is free again.
    assert await process_one_job() is False


async def test_what_a_stopped_handler_had_written_is_rolled_back(client, handler, monkeypatch):
    monkeypatch.setattr(jobs, "JOB_TIMEOUT_SECONDS", 0.05)

    async def _writes_then_hangs(session, payload):
        await enqueue(session, "never_committed", {})
        await session.flush()
        await asyncio.sleep(30)

    handler(_writes_then_hangs)
    await _queue()

    assert await asyncio.wait_for(process_one_job(), timeout=5) is True

    async with async_session() as session:
        left = await session.scalar(
            select(func.count()).select_from(Job).where(Job.type == "never_committed")
        )
    assert left == 0


async def test_a_timeout_raised_by_the_handler_itself_is_reported_as_its_own(
    client, handler, monkeypatch
):
    """Only the worker's own limit is described as the worker's limit. A
    TimeoutError from inside the handler keeps its own words."""

    async def _raises(session, payload):
        raise TimeoutError("the meeting provider did not answer")

    handler(_raises)
    await _queue()

    assert await process_one_job() is True

    job = await _the_job()
    assert job.error == "the meeting provider did not answer"
    assert job.status == JobStatus.pending


async def test_a_job_type_can_be_given_a_longer_limit(client, handler, monkeypatch):
    monkeypatch.setattr(jobs, "JOB_TIMEOUT_SECONDS", 0.05)

    async def _slow_but_fine(session, payload):
        await asyncio.sleep(0.2)

    handler(_slow_but_fine, timeout_seconds=5)
    await _queue()

    assert await process_one_job() is True
    assert (await _the_job()).status == JobStatus.done


def test_registering_sets_and_clears_a_job_types_own_limit(monkeypatch):
    monkeypatch.setattr(jobs, "_handlers", dict(jobs._handlers))
    monkeypatch.setattr(jobs, "_timeouts", dict(jobs._timeouts))

    async def _noop(session, payload):
        return None

    register_handler(JOB, _noop, timeout_seconds=1234)
    assert job_timeout_seconds(JOB) == 1234

    register_handler(JOB, _noop)
    assert job_timeout_seconds(JOB) == JOB_TIMEOUT_SECONDS


def test_the_booklet_reader_gets_room_for_both_of_its_ai_calls(monkeypatch):
    """It makes two AI calls in a row, each allowed the full AI deadline. Under
    the default limit the second would be cut short by the worker, which leaves
    the booklet showing "extracting" with no error."""
    from app.config import get_settings

    monkeypatch.setattr(jobs, "_handlers", {})
    monkeypatch.setattr(jobs, "_timeouts", {})
    register_all()

    ai_deadline = get_settings().ai_call_timeout_seconds
    assert job_timeout_seconds("extract_booklet") == 2 * ai_deadline + BOOKLET_READ_MARGIN_SECONDS
    # Every other job keeps the default.
    assert set(jobs._timeouts) == {"extract_booklet"}
    assert job_timeout_seconds("mark_submission") == JOB_TIMEOUT_SECONDS


async def test_shutting_the_worker_down_is_not_mistaken_for_the_limit(client, handler):
    """`asyncio.timeout` turns only its own cancellation into TimeoutError. A
    worker being stopped must still see CancelledError, or shutdown would be
    recorded as a failed attempt and the loop would carry on."""
    started = asyncio.Event()

    async def _waits(session, payload):
        started.set()
        await asyncio.sleep(30)

    handler(_waits)
    await _queue()

    task = asyncio.create_task(process_one_job())
    await asyncio.wait_for(started.wait(), timeout=5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    job = await _the_job()
    assert job.status == JobStatus.running, "left for the orphan sweep, as before"
    assert job.error is None


# --- No retry for a failure that cannot succeed ------------------------------


def _key_missing():
    return AIKeyMissingError("AI is not configured: set ANTHROPIC_API_KEY")


@pytest.mark.parametrize(
    "make",
    [
        _key_missing,
        lambda: AIOutputTruncatedError("cut off at the output limit (32000 tokens)"),
        lambda: AICallFailedError("The AI provider did not accept the API key", retryable=False),
        lambda: storage.ObjectNotFoundError("org/3/gone.pdf"),
    ],
    ids=["key missing", "answer cut off", "provider rejected", "file missing"],
)
async def test_a_failure_that_cannot_succeed_is_not_retried(client, handler, make):
    async def _fails(session, payload):
        raise make()

    handler(_fails)
    await _queue()

    assert await process_one_job() is True

    job = await _the_job()
    assert job.status == JobStatus.failed, "failed on the first attempt, no retry scheduled"
    assert job.attempts == 1
    assert job.run_after is None
    assert job.error == str(make())
    assert await process_one_job() is False


@pytest.mark.parametrize(
    "make",
    [
        lambda: RuntimeError("provider returned 529"),
        lambda: AITimeoutError("The AI did not answer in time"),
        lambda: AICallFailedError("The connection to the AI dropped mid-answer"),
        # The parent of the missing-key error means a deployment fault (a
        # missing optional SDK, a misrouted provider) and has always retried.
        lambda: AIUnavailableError("The google-genai package is not installed"),
        lambda: ValueError("No questions were found in the paper"),
    ],
    ids=["unknown", "ai timeout", "dropped connection", "ai unavailable", "domain error"],
)
async def test_every_other_failure_keeps_its_retry(client, handler, make):
    async def _fails(session, payload):
        raise make()

    handler(_fails)
    await _queue()

    assert await process_one_job() is True

    job = await _the_job()
    assert job.status == JobStatus.pending
    assert job.run_after is not None


def test_only_an_explicit_false_opts_out_of_the_retry():
    class Marked(Exception):
        retryable = False

    class Truthy(Exception):
        retryable = True

    class Blank(Exception):
        retryable = None

    assert is_permanent(Marked())
    assert not is_permanent(Truthy())
    assert not is_permanent(Blank()), "anything but False keeps the retry"
    assert not is_permanent(RuntimeError("x"))

    late = RuntimeError("x")
    late.retryable = False  # type: ignore[attr-defined]
    assert is_permanent(late), "an instance can opt out as well as a class"


def test_a_missing_file_reads_as_a_sentence_and_keeps_its_key():
    """Its message lands in front of a tutor (`submission.ai_error`); it used to
    be the bare storage key."""
    exc = storage.ObjectNotFoundError("org/3/ab12.pdf")
    assert str(exc) == "An uploaded file this needs is missing from storage"
    assert exc.key == "org/3/ab12.pdf"
    assert "org/3" not in str(exc)
