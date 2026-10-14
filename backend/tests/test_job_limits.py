"""The job worker's two limits: how long one job may run, and when a failure is
not worth the retry.

Until these, a handler that never returned held the only worker for good, and
every failure was retried a minute later whether or not a minute could change
anything — a missing API key, an answer cut off at the output limit and a file
that is gone all fail identically the second time, and the AI ones are billed
twice for it."""

import asyncio
import copy
import traceback

import pytest
from sqlalchemy import func, select

from app.config import get_settings
from app.db import async_session
from app.models import Job, JobStatus
from app.services import ai as ai_service
from app.services import storage
from app.services.ai import (
    AICallFailedError,
    AIKeyMissingError,
    AIOutputTruncatedError,
    AITimeoutError,
    AIUnavailableError,
)
from app.workers import jobs
from app.workers.handlers import register_all
from app.workers.jobs import (
    JOB_STALL_SECONDS,
    JOB_TIMEOUT_MARGIN_SECONDS,
    default_job_timeout_seconds,
    enqueue,
    is_permanent,
    job_timeout_seconds,
    process_one_job,
    register_handler,
)

JOB = "limits_probe"
#: A limit short enough to keep the suite fast and long enough that a slow
#: machine still gets the handler started before it fires.
SHORT = 0.25


@pytest.fixture
def handler(monkeypatch):
    """Register a handler for JOB for one test, leaving no trace in the
    process-global registry (handlers and time limits both)."""

    def _register(fn, *, timeout_seconds=None):
        monkeypatch.setitem(jobs._handlers, JOB, fn)
        monkeypatch.delitem(jobs._timeouts, JOB, raising=False)
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


def test_the_limit_follows_the_ai_deadline_and_never_drops_below_the_stall_point(monkeypatch):
    """The worker's limit has to be the longer of the two, or it cuts an AI call
    before the call's own deadline can end it as an ordinary failure the
    handler records. It is derived, so raising the AI deadline moves it."""
    settings = get_settings()
    assert settings.ai_call_timeout_seconds + JOB_TIMEOUT_MARGIN_SECONDS == JOB_STALL_SECONDS, (
        "with the default settings a job is stopped at the moment health calls it hung"
    )
    assert job_timeout_seconds("anything_unregistered") == JOB_STALL_SECONDS

    monkeypatch.setattr(settings, "ai_call_timeout_seconds", 1000.0)
    assert job_timeout_seconds("mark_submission") == 1000.0 + JOB_TIMEOUT_MARGIN_SECONDS

    monkeypatch.setattr(settings, "ai_call_timeout_seconds", 30.0)
    assert job_timeout_seconds("mark_submission") == JOB_STALL_SECONDS


def test_health_and_the_worker_agree_on_when_a_job_has_run_too_long(monkeypatch):
    """One number, read in three places. With the AI deadline raised, a job the
    worker still allows must not be reported as hung."""
    from datetime import datetime, timedelta, timezone

    from app.models import WorkerHeartbeat

    now = datetime.now(timezone.utc)

    def _state(job_seconds: float) -> str:
        row = WorkerHeartbeat(
            worker_id="w",
            started_at=now - timedelta(hours=1),
            last_loop_at=now - timedelta(seconds=job_seconds),
            job_started_at=now - timedelta(seconds=job_seconds),
            restarts=[],
        )
        return jobs._status_for(row, now).state

    assert default_job_timeout_seconds() == JOB_STALL_SECONDS
    assert _state(JOB_STALL_SECONDS + 60) == "stalled"

    monkeypatch.setattr(get_settings(), "ai_call_timeout_seconds", 1000.0)
    assert default_job_timeout_seconds() == 1000.0 + JOB_TIMEOUT_MARGIN_SECONDS
    assert _state(JOB_STALL_SECONDS + 60) == "running", "still inside the worker's limit"
    assert _state(1000.0 + JOB_TIMEOUT_MARGIN_SECONDS + 60) == "stalled"


async def test_a_handler_that_never_returns_is_stopped(client, handler):
    stopped = asyncio.Event()

    async def _hangs(session, payload):
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            stopped.set()
            raise

    handler(_hangs, timeout_seconds=SHORT)
    await _queue()

    assert await asyncio.wait_for(process_one_job(), timeout=10) is True

    assert stopped.is_set(), "the handler itself must be cancelled, not just abandoned"
    job = await _the_job()
    assert job.status == JobStatus.pending, "a stall gets the one retry, like any failure"
    assert job.error == f"The job ran past its {SHORT:g}-second time limit and was stopped"
    assert job.claimed_by is None
    assert job.claimed_at is None


async def test_a_job_stopped_twice_is_failed_and_the_queue_moves_on(client, handler):
    async def _hangs(session, payload):
        await asyncio.sleep(30)

    handler(_hangs, timeout_seconds=SHORT)
    await _queue()

    assert await asyncio.wait_for(process_one_job(), timeout=10) is True
    await _skip_backoff()
    assert await asyncio.wait_for(process_one_job(), timeout=10) is True

    job = await _the_job()
    assert job.status == JobStatus.failed
    assert job.attempts == 2
    assert "time limit" in job.error
    # The point of the limit: the worker is free again.
    assert await process_one_job() is False


async def test_what_a_stopped_handler_had_written_is_rolled_back(client, handler):
    written = asyncio.Event()

    async def _writes_then_hangs(session, payload):
        await enqueue(session, "never_committed", {})
        await session.flush()
        written.set()
        await asyncio.sleep(30)

    handler(_writes_then_hangs, timeout_seconds=SHORT)
    await _queue()

    assert await asyncio.wait_for(process_one_job(), timeout=10) is True

    assert written.is_set(), "the write must have happened, or its absence proves nothing"
    async with async_session() as session:
        left = await session.scalar(
            select(func.count()).select_from(Job).where(Job.type == "never_committed")
        )
    assert left == 0


async def test_a_timeout_raised_by_the_handler_itself_is_reported_as_its_own(client, handler):
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


async def test_an_ai_deadline_reaches_the_handler_as_an_ordinary_failure(client, handler):
    """What is lost when the worker's limit fires first, and so the reason it is
    derived to be the longer one (the derivation is pinned by the first test in
    this file). An AI deadline that expires inside a running job arrives in the
    handler as an ordinary exception: the handler's own `except` runs and
    records the failure on its row. The next test is the other half."""
    recorded: list[str] = []

    async def _marks(session, payload):
        try:
            async with ai_service._call_deadline("marking", 0.05):
                await asyncio.sleep(30)
        except Exception as exc:
            recorded.append(str(exc))  # what a real handler writes to `ai_error`
            raise

    handler(_marks, timeout_seconds=5)
    await _queue()

    assert await asyncio.wait_for(process_one_job(), timeout=10) is True

    assert recorded == ["The AI did not answer in time"]
    job = await _the_job()
    assert job.error == "The AI did not answer in time"
    assert job.status == JobStatus.pending, "an AI timeout keeps its retry"


async def test_a_handler_stopped_by_the_worker_cannot_record_its_own_failure(client, handler):
    """The known limit of the backstop, pinned so it is changed on purpose: the
    handler's `except Exception` does not run when the worker stops it."""
    recorded: list[str] = []

    async def _marks(session, payload):
        try:
            await asyncio.sleep(30)
        except Exception as exc:
            recorded.append(str(exc))
            raise

    handler(_marks, timeout_seconds=SHORT)
    await _queue()

    assert await asyncio.wait_for(process_one_job(), timeout=10) is True

    assert recorded == []
    assert "time limit" in (await _the_job()).error


async def test_a_job_type_can_be_given_its_own_limit(client, handler):
    async def _slow_but_fine(session, payload):
        await asyncio.sleep(SHORT * 2)

    handler(_slow_but_fine, timeout_seconds=10)
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
    assert job_timeout_seconds(JOB) == JOB_STALL_SECONDS


@pytest.mark.parametrize("bad", [0, -1, float("nan")])
def test_a_limit_that_would_stop_every_run_is_refused(monkeypatch, bad):
    monkeypatch.setattr(jobs, "_handlers", dict(jobs._handlers))
    monkeypatch.setattr(jobs, "_timeouts", dict(jobs._timeouts))

    async def _noop(session, payload):
        return None

    with pytest.raises(ValueError, match="must be above 0"):
        register_handler(JOB, _noop, timeout_seconds=bad)
    assert JOB not in jobs._handlers


def test_the_booklet_reader_gets_room_for_both_of_its_ai_calls(monkeypatch):
    """It makes two AI calls in a row, each allowed the full AI deadline, where
    the default limit leaves room for one."""
    monkeypatch.setattr(jobs, "_handlers", {})
    monkeypatch.setattr(jobs, "_timeouts", {})
    register_all()

    ai_deadline = get_settings().ai_call_timeout_seconds
    assert job_timeout_seconds("extract_booklet") == 2 * ai_deadline + JOB_TIMEOUT_MARGIN_SECONDS
    assert job_timeout_seconds("extract_booklet") > job_timeout_seconds("mark_submission")
    assert "mark_submission" not in jobs._timeouts, "single-call jobs keep the default"


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
        lambda: AICallFailedError(
            "The AI provider did not accept the API key", job_retryable=False
        ),
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
        job_retryable = False

    class Truthy(Exception):
        job_retryable = True

    class Blank(Exception):
        job_retryable = None

    assert is_permanent(Marked())
    assert not is_permanent(Truthy())
    assert not is_permanent(Blank()), "anything but False keeps the retry"
    assert not is_permanent(RuntimeError("x"))

    late = RuntimeError("x")
    late.job_retryable = False  # type: ignore[attr-defined]
    assert is_permanent(late), "an instance can opt out as well as a class"


def test_another_librarys_own_retryable_flag_is_not_read_as_ours():
    """google-auth's exceptions carry `retryable`, False by default, meaning
    something of their own. Under the first name this flag had, every one of
    them would have lost its retry here without anybody deciding that."""

    class TheirError(Exception):
        retryable = False

    assert not is_permanent(TheirError())


def test_a_missing_file_reads_as_a_sentence_and_keeps_its_key():
    """Its message lands in front of a tutor (`submission.ai_error`); it used to
    be the bare storage key. The key still reaches the log, as a note under the
    traceback."""
    exc = storage.ObjectNotFoundError("org/3/ab12.pdf")
    assert str(exc) == "An uploaded file this needs is missing from storage"
    assert exc.key == "org/3/ab12.pdf"
    assert "org/3" not in str(exc)
    assert "storage key: org/3/ab12.pdf" in "".join(traceback.format_exception(exc))
    assert copy.copy(exc).key == "org/3/ab12.pdf"


async def test_a_missing_file_is_logged_with_its_key_where_it_is_raised(
    caplog, tmp_path, monkeypatch
):
    monkeypatch.setattr(get_settings(), "upload_dir", str(tmp_path))
    backend = storage.LocalBackend()
    with (
        caplog.at_level("WARNING", logger=storage.log.name),
        pytest.raises(storage.ObjectNotFoundError),
    ):
        await backend.download("org/3/never-uploaded.pdf")
    assert "org/3/never-uploaded.pdf" in caplog.text
