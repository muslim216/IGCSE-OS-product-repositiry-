"""Fail if the schema Alembic just built disagrees with the SQLAlchemy models.

The test suite forces SQLite in-memory and builds its schema from
`Base.metadata` (`tests/conftest.py`), so it never runs a migration at all
(`RISK-3`, `QA-11`) — a migration can therefore drift from the models it is
meant to describe and every local/CI test still passes. This script is the
CI job's way of catching that: run it against a real database right after
`alembic upgrade head`, and it uses Alembic's own autogenerate comparison to
diff what the migrations actually built against what `Base.metadata` (the
`BE-3` barrel, so every model is included) says it should be.

Usage (from backend/): python -m scripts.check_schema_drift
Reads DATABASE_URL the same way the app does (via app.config.get_settings).

Connects with the async engine rather than adding a sync driver dependency
(no psycopg2/psycopg is installed — only asyncpg, per pyproject.toml).
`AsyncConnection.run_sync` is the same bridge alembic/env.py already uses to
hand a sync-looking `Connection` to Alembic's migration runner, so
`compare_metadata` — which is a sync API — runs inside that bridge instead.
"""

import asyncio
import sys

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import get_settings
from app.models import Base


def _compare(connection: Connection) -> list:
    ctx = MigrationContext.configure(connection)
    return compare_metadata(ctx, Base.metadata)


async def main() -> int:
    engine = create_async_engine(get_settings().database_url)
    try:
        async with engine.connect() as conn:
            diffs = await conn.run_sync(_compare)
    finally:
        await engine.dispose()

    # Noisy false positives compare_metadata is known to report, filtered
    # narrowly rather than suppressing the check's output wholesale — each
    # filter names exactly the diff shape it drops and why (CODE-12/CODE-13).
    diffs = [d for d in diffs if not _is_known_false_positive(d)]

    if not diffs:
        # Name the dialect actually checked: run locally against SQLite this
        # says nothing about Postgres, which is the dialect that matters.
        print(f"No schema drift: {conn.engine.dialect.name} schema matches Base.metadata.")
        return 0

    print(f"SCHEMA DRIFT: {len(diffs)} difference(s) between the migrations and the models:\n")
    for d in diffs:
        print(" -", d)
    return 1


def _is_known_false_positive(diff: object) -> bool:
    # Nothing filtered yet — see the report for what was actually run and
    # found. Kept as an explicit hook (rather than a bare empty list) so the
    # next genuine false positive gets a comment here instead of a silent
    # diff at the call site.
    return False


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
