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

CI's `migrations` job already stands up Postgres 16; wiring these into it is
task 1.5's job, along with the rest of the two-instance suite.
"""

import asyncio
import os

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select

from app.db import async_session, engine
from app.models import Base, Job, JobStatus
from app.workers import jobs

pytestmark = [
    pytest.mark.skipif(
        not os.environ.get("TEST_DATABASE_URL", "").startswith("postgresql"),
        reason=(
            "needs real Postgres: SQLite silently drops FOR UPDATE SKIP LOCKED, so this "
            "would pass without exercising the lock (see docs/av-82-architecture-impact-report.md)"
        ),
    ),
    # Module-scoped, not the function-scoped default: `engine` (app.db) is a
    # module-level asyncpg pool created once and shared by every test here. A
    # fresh event loop per test would leave pooled connections bound to a loop
    # that the next test's loop is not — a RuntimeError during fixture setup,
    # not a real bug in the code under test.
    pytest.mark.asyncio(loop_scope="module"),
]


@pytest_asyncio.fixture(loop_scope="module", autouse=True)
async def _db_schema():
    """Shadow conftest's function-scoped `_db_schema` for this module.

    That fixture's loop is function-scoped by default, which does not match
    the module-scoped loop the tests below run in (see the `loop_scope`
    marker above) — asyncpg connections opened while it runs would be bound
    to a loop the tests then reach from a different one, which is exactly
    the "attached to a different loop" / "another operation is in progress"
    failures this override exists to avoid. `pg_schema` below still does its
    own per-test cleanup; this only replaces the create/drop-all half.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture(loop_scope="module")
async def pg_schema():
    """Make sure the tables exist and start from an empty queue.

    `create_all` is checkfirst by default, so this is a no-op when Alembic has
    already built the schema (which is the case in CI, where these run in the
    migrations job). Only the rows this test creates are cleaned up — dropping
    the schema would fight the migration job it runs inside.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_session() as session:
        await session.execute(delete(Job))
        await session.commit()
    yield
    async with async_session() as session:
        await session.execute(delete(Job))
        await session.commit()


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

    async def _hangs(session, payload):
        started.set()
        await asyncio.sleep(30)

    jobs.register_handler("hang_probe", _hangs)

    async with async_session() as session:
        await jobs.enqueue(session, "hang_probe", {})
        await session.commit()

    task = asyncio.create_task(jobs.process_one_job())
    await asyncio.wait_for(started.wait(), timeout=5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    async with async_session() as session:
        row = await session.scalar(select(Job).where(Job.type == "hang_probe"))
    assert row is not None
    assert row.status == JobStatus.running
