"""Two workers must never run the same job (task 1.3, AV-82).

The claim query has always been safe — `.with_for_update(skip_locked=True)` in
`jobs.py` — and the plan is explicit that it must not be rewritten. What was
missing is the test, which matters now that a second worker is a deployment
away rather than impossible.

**These tests are Postgres-only, and skip on SQLite rather than passing.** The
1.1 architecture-impact report found that SQLite silently *drops* the
`FOR UPDATE SKIP LOCKED` clause — no error, no warning — so the same test on
the default suite backend would exercise a query with no locking in it, pass,
and prove nothing. A green test that proves nothing is worse than no test,
because it gets cited as evidence. Run them with a real Postgres:

    TEST_DATABASE_URL=postgresql+asyncpg://igcse:igcse@localhost:5432/igcse \\
        pytest tests/test_worker_concurrency.py

`TEST_DATABASE_URL` rather than `DATABASE_URL` because conftest.py deliberately
overrides the latter to SQLite before any app import; the opt-in name is what
lets these tests reach a real database without changing what every other test
runs against.

These run in CI's `migrations` job, which already stands up Postgres 16. That
step fails if the URL is not Postgres or if anything skips, so a green tick
cannot mean "never ran".
"""

import asyncio
import contextlib
import os

import pytest
from sqlalchemy import delete, func, select

from app.db import async_session, engine
from app.models import Base, Job, JobStatus
from app.workers import jobs

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL", "").startswith("postgresql"),
    reason=(
        "needs real Postgres: SQLite silently drops FOR UPDATE SKIP LOCKED, so this "
        "would pass without exercising the lock (see docs/av-82-architecture-impact-report.md)"
    ),
)


@pytest.fixture
async def pg_schema():
    """Make sure the tables exist and start from an empty queue.

    `create_all` is checkfirst by default, so this is a no-op when Alembic has
    already built the schema (which is the case in CI, where these run in the
    migrations job). Only the rows this test creates are cleaned up — dropping
    the schema would fight the migration job it runs inside.

    The engine is disposed at both ends. `app.db.engine` is module-level and
    pools its connections, but pytest-asyncio gives each test a fresh event
    loop — so a connection opened under one test's loop and reused by the next
    fails with "attached to a different loop", inside fixture setup, where the
    traceback points at asyncpg rather than at the cause. Disposing drops the
    pooled connections so each test opens its own. This is a real constraint on
    any Postgres test that shares this engine, so 1.5's two-instance suite will
    need the same treatment.
    """
    await engine.dispose()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_session() as session:
        await session.execute(delete(Job))
        await session.commit()
    registered_before = set(jobs._handlers)
    yield
    # `_handlers` is a process-global dict. Without this, the probe handlers
    # below — one of which sleeps — stay registered for the rest of the pytest
    # session and could be picked up by any later test that drains the queue.
    for name in set(jobs._handlers) - registered_before:
        jobs._handlers.pop(name, None)
    async with async_session() as session:
        await session.execute(delete(Job))
        await session.commit()
    await engine.dispose()


async def test_two_workers_never_claim_the_same_job(pg_schema):
    """The guarantee the whole worker split rests on."""
    ran: list[dict] = []
    lock = asyncio.Lock()

    async def _record(session, payload):
        async with lock:
            ran.append(payload)
        # Held long enough that a second claimant would overlap rather than
        # tidily follow — without SKIP LOCKED this is where the double-run shows.
        await asyncio.sleep(0.05)

    jobs.register_handler("concurrency_probe", _record)

    async with async_session() as session:
        for i in range(20):
            await jobs.enqueue(session, "concurrency_probe", {"n": i})
        await session.commit()

    async def _drain() -> None:
        while await jobs.process_one_job():
            pass

    await asyncio.gather(_drain(), _drain(), _drain(), _drain())

    assert len(ran) == 20, "every job must run exactly once"
    assert sorted(p["n"] for p in ran) == list(range(20)), "no job run twice, none skipped"

    async with async_session() as session:
        done = await session.scalar(
            select(func.count()).select_from(Job).where(Job.status == JobStatus.done)
        )
    assert done == 20


async def test_a_job_left_running_by_a_killed_worker_is_visible(pg_schema):
    """A worker killed mid-job leaves the row in `running`.

    Recording the current behaviour rather than asserting a recovery that does
    not exist yet: nothing re-queues an orphaned `running` row today. Task 1.5's
    two-instance suite covers the recovery case, and 11.5 alerts on it. Written
    down here so the gap is a known one rather than a surprise.
    """
    started = asyncio.Event()
    release = asyncio.Event()

    async def _hangs(session, payload):
        started.set()
        # Waits on an event rather than sleeping a fixed interval: the test
        # cancels this deliberately, and a wall-clock sleep would decide how
        # long a leaked task lingers if anything ever went wrong here.
        await release.wait()

    jobs.register_handler("hang_probe", _hangs)

    async with async_session() as session:
        await jobs.enqueue(session, "hang_probe", {})
        await session.commit()

    task = asyncio.create_task(jobs.process_one_job())
    try:
        # Generous, because this only ever runs in CI against a cold asyncpg
        # connection under variable load; it bounds a hang, it does not pace
        # the test.
        await asyncio.wait_for(started.wait(), timeout=30)
    finally:
        # In a finally so a timeout cannot leave the task pending — that would
        # surface as "Task was destroyed but it is pending" and obscure the
        # real failure.
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    # The cancelled task held an asyncpg connection mid-transaction — that is
    # the whole point of simulating a hard kill. But the pool does not know
    # the connection is unusable, and handing it to the next checkout raises
    # deep inside asyncpg rather than cleanly. Disposing forces a fresh
    # connection for the read below and for whatever runs after this test,
    # rather than leaking a corrupt one into either.
    await engine.dispose()

    async with async_session() as session:
        row = await session.scalar(select(Job).where(Job.type == "hang_probe"))
    assert row is not None
    assert row.status == JobStatus.running
