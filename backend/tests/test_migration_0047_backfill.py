"""The 0047 backfill, run against rows that actually exist.

Everything else in this suite builds its schema from `Base.metadata` and never
runs a migration, and CI's up/down/up runs against an empty Postgres — so
without this test the backfill loop's first real execution would be production,
on the one dataset nobody can re-run. `RISK-3` is the record of that class of
bug biting twice here already.

Subprocess and a temporary file database rather than the suite's in-memory one:
`conftest.py` pins `DATABASE_URL` to `sqlite+aiosqlite:///:memory:` before any
app import, and alembic needs a database that outlives a single connection.
"""

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent


def _alembic(db: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND,
        env={**os.environ, "DATABASE_URL": f"sqlite+aiosqlite:///{db}"},
        capture_output=True,
        text=True,
    )


def test_existing_work_is_adopted_and_the_pointer_becomes_required(tmp_path) -> None:
    db = tmp_path / "backfill.db"
    at_0046 = _alembic(db, "upgrade", "0046")
    assert at_0046.returncode == 0, at_0046.stderr

    # Rows as the previous revision left them: no parent, and an assignment
    # whose organization and subject are only knowable through its group.
    raw = sqlite3.connect(db)
    raw.executescript("""
        INSERT INTO organizations (id, name, created_at) VALUES (1, 'Org', '2026-01-01 00:00:00');
        INSERT INTO subjects (id, organization_id, exam_board, code, name, level, grade_scale)
            VALUES (1, 1, 'Edexcel IGCSE', '4CH1', 'Chemistry', 'igcse', '9-1');
        INSERT INTO users (id, organization_id, name, role, password_hash, token_version, created_at)
            VALUES (1, 1, 'T', 'tutor', 'x', 0, '2026-01-01 00:00:00');
        INSERT INTO groups (id, organization_id, tutor_id, subject_id, name, created_at)
            VALUES (1, 1, 1, 1, 'Y11', '2026-01-01 00:00:00');
        INSERT INTO assignments (id, group_id, title, status, created_at)
            VALUES (1, 1, 'Old homework', 'published', '2026-01-01 00:00:00');
        INSERT INTO booklets (id, organization_id, subject_id, status, created_at)
            VALUES (1, 1, 1, 'applied', '2026-01-01 00:00:00');
        INSERT INTO past_papers (id, organization_id, subject_id, booklet_id, booklet_index, created_at)
            VALUES (1, 1, 1, 1, 1, '2026-01-01 00:00:00');
        INSERT INTO mocks (id, organization_id, tutor_id, subject_id, title, type,
                           paper_path, paper_name, paper_mime, status, created_at)
            VALUES (1, 1, 1, 1, 'Mock 1', 'mock', 'p', 'p.pdf', 'application/pdf',
                    'ready', '2026-01-01 00:00:00');
    """)
    raw.commit()

    applied = _alembic(db, "upgrade", "head")
    assert applied.returncode == 0, applied.stderr

    rows = dict(raw.execute("SELECT kind, COUNT(*) FROM assessable_work GROUP BY kind").fetchall())
    assert rows == {"homework": 1, "past_paper": 1, "mock": 1}

    # The assignment is the arm that carries neither column itself.
    org, subject, title = raw.execute("""
        SELECT w.organization_id, w.subject_id, w.title
        FROM assignments a JOIN assessable_work w ON w.id = a.work_id
    """).fetchone()
    assert (org, subject, title) == (1, 1, "Old homework")

    # A past paper is unnamed until extraction runs; the parent says so too.
    assert (
        raw.execute("""
        SELECT w.title FROM past_papers p JOIN assessable_work w ON w.id = p.work_id
    """).fetchone()[0]
        is None
    )

    for table in ("assignments", "past_papers", "mocks"):
        total, parented = raw.execute(
            f"SELECT COUNT(*), COUNT(work_id) FROM {table}"  # noqa: S608 - fixed names
        ).fetchone()
        assert total == parented, f"{table} left {total - parented} rows without a parent"

    # And the pointer is now required.
    with pytest.raises(sqlite3.IntegrityError):
        raw.execute(
            "INSERT INTO assignments (id, group_id, title, status, created_at)"
            " VALUES (2, 1, 'No parent', 'published', '2026-01-01 00:00:00')"
        )

    # That failed INSERT left this connection holding a write transaction, and
    # alembic cannot take the lock until it is released.
    raw.rollback()

    reverted = _alembic(db, "downgrade", "0046")
    assert reverted.returncode == 0, reverted.stderr
    assert raw.execute("SELECT COUNT(*) FROM assessable_work").fetchone()[0] == 0
    assert raw.execute("SELECT COUNT(work_id) FROM assignments").fetchone()[0] == 0
    raw.close()
