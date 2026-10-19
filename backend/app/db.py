from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.config import get_settings

#: No single statement runs longer than this. A query that slow at our size is
#: a bug, and without a ceiling it holds its connection, and every row it
#: locked, for as long as it takes (`DB-01`). Postgres only; migrations build
#: their own engine (`alembic/env.py`) and are not held to it.
STATEMENT_TIMEOUT_MS = 60_000

#: A connection is replaced after this long, before a provider's idle cut-off
#: can close it under a request.
POOL_RECYCLE_SECONDS = 1800


def _engine_kwargs(url: str, *, pool_size: int, max_overflow: int) -> dict[str, Any]:
    # In-memory SQLite needs a single shared connection or each session
    # would see an empty database (used by the test suite).
    if url.startswith("sqlite") and ":memory:" in url:
        return {"poolclass": StaticPool, "connect_args": {"check_same_thread": False}}
    if not url.startswith("postgresql"):
        return {}
    return {
        "pool_size": pool_size,
        "max_overflow": max_overflow,
        # A connection the server or the provider dropped while idle is found
        # and replaced before a request gets it, instead of that request
        # failing with "connection is closed" (`OPS-16`).
        "pool_pre_ping": True,
        "pool_recycle": POOL_RECYCLE_SECONDS,
        # Sent as a startup parameter, which Render's Postgres takes directly.
        # Behind a PgBouncer this needs `ignore_startup_parameters` set there
        # (and asyncpg's statement cache off in transaction pooling).
        "connect_args": {"server_settings": {"statement_timeout": str(STATEMENT_TIMEOUT_MS)}},
    }


settings = get_settings()
engine = create_async_engine(
    settings.database_url,
    **_engine_kwargs(
        settings.database_url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
    ),
)
async_session = async_sessionmaker(engine, expire_on_commit=False)


async def release_connection(session: AsyncSession) -> None:
    """End the session's transaction before a long wait, a model call above all,
    which can take minutes. Its connection then goes back to the pool for that
    time instead of sitting idle in a transaction with its row locks held
    (`CAP-6`, `DB-01`); the next statement takes a fresh one.

    It commits whatever is pending, so it belongs only where the writes made so
    far are fine to keep if the call then fails. Loaded objects stay usable
    (`expire_on_commit=False`), though they are no fresher than before."""
    await session.commit()


async def get_db() -> AsyncIterator[AsyncSession]:
    async with async_session() as session:
        yield session
