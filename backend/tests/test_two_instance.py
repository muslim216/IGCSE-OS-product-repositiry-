"""Task 1.5 (AV-84): the two-instance correctness suite.

A hard acceptance requirement for Phase 1. Phase 1 built the capability to run
more than one API and more than one worker (`RISK-1`'s three links: object
storage in 1.2, a standalone worker in 1.3, shared rate-limit counters in 1.4).
Nothing had ever checked that two of anything actually behave.

**What "two instances" means here, precisely.** Not two processes — the suite
runs in one. What it does is give each simulated instance its **own copy of the
process-local state** an instance owns (its storage backend object, its rate
limiter, its worker identity) while pointing them at the **one shared store**
they must agree through. That is exactly where a scale-out bug lives: state a
second instance cannot see. Two objects over one Postgres, one Redis and one
bucket reproduces it; two processes would cost a fixture harness and prove the
same thing.

**Postgres-only, and skipping is a failure, not a pass.** SQLite silently drops
`FOR UPDATE SKIP LOCKED`, so a concurrency test there exercises a query with no
locking in it and proves nothing — the lesson from 1.3, restated because this
suite is the one most likely to be cited as evidence. The storage case needs a
real S3-compatible store and the login case a real Redis, both for the same
reason. Each is gated on its own environment variable and CI supplies all three.

    TEST_DATABASE_URL=postgresql+asyncpg://igcse:igcse@localhost:5432/igcse \\
    TEST_REDIS_URL=redis://localhost:6379/0 \\
    TEST_S3_ENDPOINT_URL=http://localhost:9000 \\
        pytest tests/test_two_instance.py

**Scope.** These cover the *distributed* properties — what breaks when there are
two. Each handler's own "safe to re-run on the same payload" duty (`BE-6`) is
covered by its own tests on the default suite (`test_narrative.py`,
`test_homework.py`), and this suite depends on that rather than repeating it.
"""

import asyncio
import contextlib
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select

from app.config import get_settings
from app.db import async_session, engine
from app.models import Base, Job, JobStatus, WorkerHeartbeat
from app.services.rate_limit import RateLimiter
from app.workers import jobs

REDIS_URL = os.environ.get("TEST_REDIS_URL")
S3_ENDPOINT = os.environ.get("TEST_S3_ENDPOINT_URL")

needs_redis = pytest.mark.skipif(not REDIS_URL, reason="TEST_REDIS_URL is not set")
needs_s3 = pytest.mark.skipif(not S3_ENDPOINT, reason="TEST_S3_ENDPOINT_URL is not set")

pytestmark = [
    pytest.mark.skipif(
        not os.environ.get("TEST_DATABASE_URL", "").startswith("postgresql"),
        reason=(
            "needs real Postgres: SQLite silently drops FOR UPDATE SKIP LOCKED, so these "
            "would pass without exercising the lock (docs/av-82-architecture-impact-report.md)"
        ),
    ),
    # Module-scoped, matching test_worker_concurrency.py: `app.db.engine` is a
    # module-level asyncpg pool, and a fresh loop per test leaves pooled
    # connections bound to a loop the next test is not in — a RuntimeError
    # raised inside fixture setup, where the traceback points at asyncpg rather
    # than at the cause.
    pytest.mark.asyncio(loop_scope="module"),
]


@pytest_asyncio.fixture(loop_scope="module", autouse=True)
async def _db_schema():
    """Shadow conftest's function-scoped `_db_schema` for this module.

    Creates only. It deliberately does **not** drop: `TEST_DATABASE_URL` points
    `DATABASE_URL` at a real database, so a `drop_all` here would delete the
    schema CI's migrations job just built and verified, and against any other
    Postgres it is straightforward data loss.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield


@pytest_asyncio.fixture(loop_scope="module")
async def queue():
    """An empty queue and an empty worker table, restored afterwards.

    Only this module's rows are removed — see `_db_schema` on why the schema
    itself is not touched.
    """

    async def _clear():
        async with async_session() as session:
            await session.execute(delete(Job))
            await session.execute(delete(WorkerHeartbeat))
            await session.commit()

    await _clear()
    registered_before = set(jobs._handlers)
    saved = (jobs._worker_registered, jobs._last_heartbeat_write)
    yield
    # `_handlers` is a process-global. Without this, probe handlers — one of
    # which blocks — stay registered for the rest of the session and could be
    # picked up by any later test that drains the queue.
    for name in set(jobs._handlers) - registered_before:
        jobs._handlers.pop(name, None)
    jobs._worker_registered, jobs._last_heartbeat_write = saved
    await _clear()


async def _drain() -> None:
    while await jobs.process_one_job():
        pass


async def _run_until_claimed(started: asyncio.Event) -> asyncio.Task:
    """Start one job and return once its handler is actually in flight."""
    task = asyncio.create_task(jobs.process_one_job())
    try:
        # Generous: this only ever runs in CI against a cold asyncpg connection
        # under variable load. It bounds a hang, it does not pace the test.
        await asyncio.wait_for(started.wait(), timeout=30)
    except BaseException:
        task.cancel()
        with contextlib.suppress(BaseException):
            await task
        raise
    return task


async def _kill(task: asyncio.Task) -> None:
    """Cancel a task mid-transaction, the way `SIGKILL` takes a worker.

    Disposing the engine afterwards is not tidiness. The cancelled task
    abandoned an asyncpg connection mid-transaction; the pool does not know it
    is unusable, and the next checkout fails deep inside asyncpg with an error
    that describes neither this test nor the code under test.
    """
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    await engine.dispose()


# --------------------------------------------------------------------------- #
# 1. Upload through API #1, retrieve and process through API #2.
# --------------------------------------------------------------------------- #


@needs_s3
async def test_a_file_written_by_one_instance_is_readable_by_another(monkeypatch):
    """The acceptance case, against a real object store.

    Two `S3Backend` objects stand in for two API instances: separate clients,
    separate connection pools, one bucket. The DB row carries a key, never a
    path, which is what makes the second instance able to serve bytes it never
    wrote.
    """
    from app.services.storage import S3Backend

    settings = get_settings()
    monkeypatch.setattr(settings, "storage_backend", "s3")
    monkeypatch.setattr(settings, "s3_endpoint_url", S3_ENDPOINT)
    monkeypatch.setattr(settings, "s3_bucket", os.environ.get("TEST_S3_BUCKET", "avora-test"))
    monkeypatch.setattr(settings, "s3_region", os.environ.get("TEST_S3_REGION", "us-east-1"))
    monkeypatch.setattr(settings, "s3_access_key_id", os.environ.get("TEST_S3_ACCESS_KEY_ID"))
    monkeypatch.setattr(
        settings, "s3_secret_access_key", os.environ.get("TEST_S3_SECRET_ACCESS_KEY")
    )

    api_one = S3Backend()
    api_two = S3Backend()
    key = f"test-two-instance/{uuid.uuid4().hex}.bin"
    payload = b"written by api #1"

    try:
        await api_one.upload(key, payload, "application/octet-stream")

        assert await api_two.exists(key) is True
        assert await api_two.download(key) == payload
    finally:
        with contextlib.suppress(Exception):
            await api_one.delete(key)


async def test_two_local_backends_do_not_share_and_that_is_why_s3_is_required(monkeypatch):
    """The negative that explains the deployment rule.

    `LocalBackend` resolves a key against this process's `UPLOAD_DIR`. Two
    instances mean two disks, so the file API #1 wrote is simply absent for API
    #2 — a 404 on a row that plainly exists. This is the first link of `RISK-1`
    stated as a test rather than as prose, and it is why `STORAGE_BACKEND=s3` is
    a precondition of scaling out rather than a preference.

    Needs no object store, unlike its positive counterpart above — it is the
    case that must stay true if anyone ever proposes shipping two instances on
    local disks. (It still carries the module's Postgres gate, which costs
    nothing: this suite is run as a unit.)
    """
    import tempfile

    from app.services.storage import LocalBackend

    key = "shared/key.bin"
    settings = get_settings()

    monkeypatch.setattr(settings, "upload_dir", tempfile.mkdtemp())
    await LocalBackend().upload(key, b"written by api #1", "application/octet-stream")

    monkeypatch.setattr(settings, "upload_dir", tempfile.mkdtemp())
    assert await LocalBackend().exists(key) is False


# --------------------------------------------------------------------------- #
# 2. Failed logins spread across both APIs still trip one shared limit.
# --------------------------------------------------------------------------- #


@needs_redis
async def test_failed_logins_split_across_two_apis_trip_one_limit(monkeypatch):
    """Ten failures split five and five must lock the account, not give it
    twenty.

    Each `RateLimiter` has its own in-process counter and both point at one
    Redis, which is the shape two API instances have. The local counters are
    asserted *not* to have reached the limit, so a silent fall back to
    per-instance counting fails this rather than passing it.
    """
    monkeypatch.setattr(get_settings(), "redis_url", REDIS_URL)
    limit = 10
    api_one = RateLimiter(purpose="login_2i", limit=limit, window_seconds=900)
    api_two = RateLimiter(purpose="login_2i", limit=limit, window_seconds=900)
    identifier = f"target-{uuid.uuid4().hex}@example.com"

    try:
        for _ in range(limit // 2):
            await api_one.record(identifier)
            await api_two.record(identifier)

        assert await api_one.is_limited(identifier) is True
        assert await api_two.is_limited(identifier) is True
        # Neither instance saw enough failures to reach the limit alone.
        assert api_one.local.is_limited(api_one.key(identifier)) is False
        assert api_two.local.is_limited(api_two.key(identifier)) is False
        assert api_one.degradation.degraded is False, "must not have fallen back"

        # And a success on either instance clears it for both.
        await api_two.reset(identifier)
        assert await api_one.is_limited(identifier) is False
    finally:
        with contextlib.suppress(Exception):
            await api_one.reset(identifier)
        for limiter in (api_one, api_two):
            with contextlib.suppress(Exception):
                await limiter.close()


# --------------------------------------------------------------------------- #
# 3. One submission never produces two marking operations.
# --------------------------------------------------------------------------- #


async def test_one_job_produces_one_operation_under_four_workers(queue):
    """A single enqueued job runs exactly once, however many workers race.

    Marking is the case that matters — a submission marked twice bills two AI
    calls and can write two sets of `QuestionMark` drafts — but the guarantee is
    the queue's, not marking's, so it is tested where it lives. That marking
    itself survives a legitimate re-run (`BE-6`, at-least-once delivery) is
    `test_homework.py`'s job.
    """
    operations: list[dict] = []
    lock = asyncio.Lock()

    async def _mark(session, payload):
        async with lock:
            operations.append(payload)
        # Held long enough that a second claimant would overlap rather than
        # tidily follow — without SKIP LOCKED this is where a double-run shows.
        await asyncio.sleep(0.05)

    jobs.register_handler("mark_probe", _mark)
    async with async_session() as session:
        await jobs.enqueue(session, "mark_probe", {"submission_id": 1})
        await session.commit()

    await asyncio.gather(_drain(), _drain(), _drain(), _drain())

    assert operations == [{"submission_id": 1}], "exactly one marking operation"


# --------------------------------------------------------------------------- #
# 4. One weekly send produces one output, even when a worker is killed mid-job.
# --------------------------------------------------------------------------- #


async def test_a_killed_sweep_does_not_double_send(queue):
    """The weekly fan-out, killed halfway and retried.

    This codebase's weekly send is the parent-narrative sweep: it re-derives who
    is due and enqueues one narrative each. Killed mid-run and re-run, it must
    still produce **one** unit of work per recipient, not two — the same
    property a mailer needs, expressed against the fan-out this system actually
    has.

    The dedupe is `narrative._pending_payloads`, mirrored by `_undelivered`
    below, which is why the re-run adds nothing: a recipient with a pending job
    is skipped. Without it the retry that at-least-once delivery guarantees
    would double every send.
    """
    started = asyncio.Event()
    release = asyncio.Event()
    recipients = [{"student_id": n} for n in (1, 2, 3)]

    async def _undelivered(session, candidates):
        pending = (
            await session.scalars(
                select(Job.payload).where(Job.type == "send_probe", Job.status == JobStatus.pending)
            )
        ).all()
        seen = {p["student_id"] for p in pending}
        return [c for c in candidates if c["student_id"] not in seen]

    async def _sweep(session, payload):
        # Fan out first, then block: the kill lands after the work is written
        # but before the job is marked done, which is the dangerous window.
        for recipient in await _undelivered(session, recipients):
            await jobs.enqueue(session, "send_probe", recipient)
        await session.commit()
        started.set()
        await release.wait()

    async def _send(session, payload):
        await asyncio.sleep(0)

    jobs.register_handler("sweep_probe", _sweep)
    jobs.register_handler("send_probe", _send)

    async with async_session() as session:
        await jobs.enqueue(session, "sweep_probe", {})
        await session.commit()

    await _kill(await _run_until_claimed(started))

    # The retry the queue owes it. Re-running the sweep must add nothing.
    started.clear()
    release.set()
    async with async_session() as session:
        await session.execute(delete(Job).where(Job.type == "sweep_probe"))
        await jobs.enqueue(session, "sweep_probe", {})
        await session.commit()
    await jobs.process_one_job()

    async with async_session() as session:
        sends = (await session.scalars(select(Job.payload).where(Job.type == "send_probe"))).all()
    assert len(sends) == len(recipients), f"one send per recipient, got {sends}"


# --------------------------------------------------------------------------- #
# 5. A worker killed halfway through a job recovers with no duplicate effects.
# --------------------------------------------------------------------------- #


async def test_a_job_orphaned_by_a_dead_worker_is_requeued_and_runs(queue):
    """The gap task 1.5 exists to close.

    Until now `running` was the queue's one unrecoverable state: no retry path
    looked at it, so a worker killed mid-job left the row there permanently and
    the work simply stopped.
    `test_worker_concurrency.py::test_a_job_left_running_by_a_killed_worker_is_visible`
    recorded that rather than asserting a recovery that did not exist.

    The recovery runs the handler a second time, which is safe only because
    `BE-6` requires every handler to be re-runnable on the same payload. The
    probe here is written that way — keyed by payload, not appended — so "no
    duplicate side effects" is asserted as one effect, not one call.
    """
    runs: list[dict] = []
    effects: set[int] = set()
    started = asyncio.Event()
    release = asyncio.Event()

    async def _handler(session, payload):
        runs.append(payload)
        # Idempotent by key, the shape BE-6 requires: a second run reaches the
        # same end state rather than adding to it.
        effects.add(payload["n"])
        if not started.is_set():
            started.set()
            await release.wait()

    jobs.register_handler("orphan_probe", _handler)
    async with async_session() as session:
        await jobs.enqueue(session, "orphan_probe", {"n": 7})
        await session.commit()

    jobs._worker_registered = True
    await jobs.register_worker()
    await _kill(await _run_until_claimed(started))

    # The row is stuck exactly as a real kill leaves it.
    async with async_session() as session:
        row = await session.scalar(select(Job).where(Job.type == "orphan_probe"))
        assert row.status is JobStatus.running
        assert row.claimed_by == jobs.WORKER_ID

    # The dead process's heartbeat row is gone — reaped by whichever worker
    # registered next, which is what a restart does. That absence is the sweep's
    # entire signal.
    async with async_session() as session:
        await session.execute(delete(WorkerHeartbeat))
        await session.commit()
    jobs._worker_registered = False

    # `now` is pushed past ORPHAN_RECLAIM_SECONDS rather than sleeping it: the
    # grace is two hours, and a test must not encode a wait to prove a cutoff.
    future = datetime.now(timezone.utc) + timedelta(seconds=jobs.ORPHAN_RECLAIM_SECONDS + 60)
    assert await jobs.reclaim_orphaned_jobs(now=future) == 1

    release.set()
    await _drain()

    async with async_session() as session:
        row = await session.scalar(select(Job).where(Job.type == "orphan_probe"))
    assert row.status is JobStatus.done
    assert row.claimed_by is None, "a finished job is held by nobody"
    assert len(runs) == 2, "at-least-once: the handler ran again after recovery"
    assert effects == {7}, "and the side effect happened once"


async def test_a_job_held_by_a_live_worker_is_never_reclaimed(queue):
    """The half that makes the repair safe rather than a duplicate-execution bug.

    A worker part-way through a slow marking call has a deliberately stale
    `last_loop_at` — the loop clock is stamped before each claim, not during the
    work — so a staleness-based sweep would hand its job to a second worker
    while the first still held it. The predicate is the claimant's heartbeat row
    being *absent*, and a live worker always has one.
    """
    async with async_session() as session:
        await jobs.enqueue(session, "never_run", {})
        await session.commit()
        job = await session.scalar(select(Job))
        job.status = JobStatus.running
        job.claimed_by = "worker-that-is-alive"
        job.claimed_at = datetime.now(timezone.utc)
        stale = datetime.now(timezone.utc) - timedelta(days=1)
        session.add(
            WorkerHeartbeat(
                worker_id="worker-that-is-alive",
                started_at=stale,
                # Deliberately ancient: this worker looks stale and is not gone.
                last_loop_at=stale,
                job_started_at=stale,
                restarts=[],
            )
        )
        await session.commit()

    future = datetime.now(timezone.utc) + timedelta(seconds=jobs.ORPHAN_RECLAIM_SECONDS + 60)
    assert await jobs.reclaim_orphaned_jobs(now=future) == 0

    async with async_session() as session:
        row = await session.scalar(select(Job))
    assert row.status is JobStatus.running, "a live worker's job stays its own"


async def test_a_recently_claimed_job_is_left_alone(queue):
    """The grace period. A claim younger than `ORPHAN_RECLAIM_SECONDS` is not
    reconsidered even with no heartbeat row, because a worker whose row was just
    reaped mid-job re-registers rather than dying (§3.3)."""
    async with async_session() as session:
        await jobs.enqueue(session, "never_run", {})
        await session.commit()
        job = await session.scalar(select(Job))
        job.status = JobStatus.running
        job.claimed_by = "worker-with-no-row"
        job.claimed_at = datetime.now(timezone.utc)
        await session.commit()

    assert await jobs.reclaim_orphaned_jobs() == 0


async def test_an_orphan_out_of_attempts_fails_instead_of_looping(queue):
    """A row whose every claim died must end, not cycle.

    Requeueing unconditionally would turn the stuck state this sweep exists to
    end into a slower version of itself: running -> pending -> running forever,
    with a worker dying each lap.
    """
    async with async_session() as session:
        await jobs.enqueue(session, "never_run", {})
        await session.commit()
        job = await session.scalar(select(Job))
        job.status = JobStatus.running
        job.attempts = jobs.MAX_ATTEMPTS
        job.claimed_by = "worker-that-died"
        job.claimed_at = datetime.now(timezone.utc)
        await session.commit()

    future = datetime.now(timezone.utc) + timedelta(seconds=jobs.ORPHAN_RECLAIM_SECONDS + 60)
    assert await jobs.reclaim_orphaned_jobs(now=future) == 1

    async with async_session() as session:
        row = await session.scalar(select(Job))
    assert row.status is JobStatus.failed
    assert "no attempts left" in row.error


async def test_two_sweeps_running_at_once_reclaim_each_row_once(queue):
    """Two workers restarting together must not both repair the same row.

    `SKIP LOCKED`, for the same reason the claim query uses it — and the count
    is the assertion, because a row reclaimed twice is a job dispatched twice.
    """
    async with async_session() as session:
        for n in range(10):
            await jobs.enqueue(session, "never_run", {"n": n})
        await session.commit()
        rows = (await session.scalars(select(Job))).all()
        for row in rows:
            row.status = JobStatus.running
            row.claimed_by = "worker-that-died"
            row.claimed_at = datetime.now(timezone.utc)
        await session.commit()

    future = datetime.now(timezone.utc) + timedelta(seconds=jobs.ORPHAN_RECLAIM_SECONDS + 60)
    counts = await asyncio.gather(
        jobs.reclaim_orphaned_jobs(now=future),
        jobs.reclaim_orphaned_jobs(now=future),
    )

    assert sum(counts) == 10, f"each row reclaimed exactly once, got {counts}"
    async with async_session() as session:
        pending = await session.scalar(
            select(func.count()).select_from(Job).where(Job.status == JobStatus.pending)
        )
    assert pending == 10
