"""The engine settings production gets (`DB-01`, `OPS-16`): the suite itself
runs on in-memory SQLite, so these are checked as arguments, not by connecting."""

from sqlalchemy.pool import StaticPool

from app.db import STATEMENT_TIMEOUT_MS, _engine_kwargs

PG = "postgresql+asyncpg://u:p@db:5432/avora"


def test_postgres_gets_a_sized_pool_that_checks_its_connections():
    kwargs = _engine_kwargs(PG, pool_size=7, max_overflow=3)
    assert kwargs["pool_size"] == 7
    assert kwargs["max_overflow"] == 3
    assert kwargs["pool_pre_ping"] is True
    assert kwargs["pool_recycle"] > 0


def test_postgres_statements_have_a_ceiling():
    settings = _engine_kwargs(PG, pool_size=1, max_overflow=0)["connect_args"]["server_settings"]
    assert settings["statement_timeout"] == str(STATEMENT_TIMEOUT_MS)


def test_in_memory_sqlite_keeps_one_shared_connection():
    kwargs = _engine_kwargs("sqlite+aiosqlite:///:memory:", pool_size=7, max_overflow=3)
    assert kwargs["poolclass"] is StaticPool
    assert "pool_size" not in kwargs
