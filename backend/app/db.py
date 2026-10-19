from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.config import get_settings

#: No single statement runs longer than this. A query that slow at our size is
#: a bug, and without a ceiling it holds its connection, and every row it
#: locked, for as long as it takes (`DB-01`). Postgres only; migrations build
#: their own engine (`alembic/env.py`) and are not held to it.
STATEMENT_TIMEOUT_MS = 60_000


def _engine_kwargs(url: str, *, pool_size: int, max_overflow: int) -> dict:
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
        "pool_recycle": 1800,
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


async def get_db() -> AsyncIterator[AsyncSession]:
    async with async_session() as session:
        yield session
