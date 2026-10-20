"""The engine settings production gets (`DB-01`, `OPS-16`): the suite itself
runs on in-memory SQLite, so these are checked as arguments, not by connecting."""

from sqlalchemy.exc import TimeoutError as PoolTimeoutError
from sqlalchemy.pool import StaticPool

from app.db import POOL_TIMEOUT_SECONDS, STATEMENT_TIMEOUT_MS, _engine_kwargs, get_db
from app.main import app

PG = "postgresql+asyncpg://u:p@db:5432/avora"


def test_postgres_gets_a_sized_pool_that_checks_its_connections():
    kwargs = _engine_kwargs(PG, pool_size=7, max_overflow=3)
    assert kwargs["pool_size"] == 7
    assert kwargs["max_overflow"] == 3
    assert kwargs["pool_pre_ping"] is True
    assert kwargs["pool_recycle"] > 0
    assert kwargs["pool_timeout"] == POOL_TIMEOUT_SECONDS


def test_postgres_statements_have_a_ceiling():
    settings = _engine_kwargs(PG, pool_size=1, max_overflow=0)["connect_args"]["server_settings"]
    assert settings["statement_timeout"] == str(STATEMENT_TIMEOUT_MS)


def test_in_memory_sqlite_keeps_one_shared_connection():
    kwargs = _engine_kwargs("sqlite+aiosqlite:///:memory:", pool_size=7, max_overflow=3)
    assert kwargs["poolclass"] is StaticPool
    assert "pool_size" not in kwargs


def test_any_other_database_gets_the_driver_defaults():
    assert _engine_kwargs("sqlite+aiosqlite:///./dev.db", pool_size=7, max_overflow=3) == {}


async def test_a_request_with_no_free_connection_is_told_busy_not_500(client, tutor):
    """Every connection taken past the pool wait: a 503 with Retry-After the page
    can act on, not a 500 that reads as a bug (`CAP-16`)."""

    async def exhausted_pool():
        raise PoolTimeoutError("QueuePool limit reached, connection timed out")
        yield  # pragma: no cover - makes this a generator dependency like get_db

    app.dependency_overrides[get_db] = exhausted_pool
    try:
        resp = await client.get("/api/v1/groups", headers=tutor["headers"])
    finally:
        app.dependency_overrides.pop(get_db, None)
    assert resp.status_code == 503
    assert resp.headers["Retry-After"] == "5"
    assert "busy" in resp.json()["detail"]
    assert resp.headers["X-Request-ID"]
