"""The 0048 backfill, run against rows that actually exist.

Mirrors `test_migration_0047_backfill.py`: subprocess alembic against a
temp file-backed SQLite DB, raw sqlite3 inserts for legacy rows, then
assertions on the migrated schema. A migration that only ever ran against
CI's empty Postgres and the in-memory test schema is a migration nobody has
actually run (`RISK-3`).
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


# Common rows every fixture below needs just to satisfy FKs: one org, one
# tutor, one subject, one group, one booklet — none of it under test.
_SCAFFOLD = """
    INSERT INTO organizations (id, name, created_at) VALUES (1, 'Org', '2026-01-01 00:00:00');
    INSERT INTO subjects (id, organization_id, exam_board, code, name, level, grade_scale)
        VALUES (1, 1, 'Edexcel IGCSE', '4CH1', 'Chemistry', 'igcse', '9-1');
    INSERT INTO users (id, organization_id, name, role, password_hash, token_version, created_at)
        VALUES (1, 1, 'T', 'tutor', 'x', 0, '2026-01-01 00:00:00');
    INSERT INTO groups (id, organization_id, tutor_id, subject_id, name, created_at)
        VALUES (1, 1, 1, 1, 'Y11', '2026-01-01 00:00:00');
    INSERT INTO booklets (id, organization_id, subject_id, status, created_at)
        VALUES (1, 1, 1, 'applied', '2026-01-01 00:00:00');
"""


def test_each_arm_backfills_to_its_own_parent(tmp_path) -> None:
    db = tmp_path / "arms.db"
    at_0047 = _alembic(db, "upgrade", "0047")
    assert at_0047.returncode == 0, at_0047.stderr

    raw = sqlite3.connect(db)
    raw.executescript(
        _SCAFFOLD
        + """
        -- Three distinct assessable_work ids, none of them 1, so a
        -- submission that picked up the wrong arm's parent would land on
        -- the wrong number rather than accidentally passing.
        INSERT INTO assessable_work (id, organization_id, subject_id, kind, created_at)
            VALUES (11, 1, 1, 'homework', '2026-01-01 00:00:00');
        INSERT INTO assessable_work (id, organization_id, subject_id, kind, created_at)
            VALUES (22, 1, 1, 'past_paper', '2026-01-01 00:00:00');
        INSERT INTO assessable_work (id, organization_id, subject_id, kind, created_at)
            VALUES (33, 1, 1, 'mock', '2026-01-01 00:00:00');

        INSERT INTO assignments (id, group_id, title, status, created_at, work_id)
            VALUES (101, 1, 'Homework', 'published', '2026-01-01 00:00:00', 11);
        INSERT INTO past_papers (id, organization_id, subject_id, booklet_id, booklet_index,
                                  created_at, work_id)
            VALUES (102, 1, 1, 1, 1, '2026-01-01 00:00:00', 22);
        INSERT INTO mocks (id, organization_id, tutor_id, subject_id, title, type,
                           paper_path, paper_name, paper_mime, status, created_at, work_id)
            VALUES (103, 1, 1, 1, 'Mock 1', 'mock', 'p', 'p.pdf', 'application/pdf',
                    'ready', '2026-01-01 00:00:00', 33);

        -- One submission per arm, each carrying only its own key.
        INSERT INTO submissions (id, assignment_id, past_paper_id, mock_id, student_id,
                                  status, submitted_at, created_at)
            VALUES (201, 101, NULL, NULL, 1, 'needs_review',
                    '2026-01-02 00:00:00', '2026-01-02 00:00:00');
        INSERT INTO submissions (id, assignment_id, past_paper_id, mock_id, student_id,
                                  status, submitted_at, created_at)
            VALUES (202, NULL, 102, NULL, 1, 'needs_review',
                    '2026-01-02 00:00:00', '2026-01-02 00:00:00');
        INSERT INTO submissions (id, assignment_id, past_paper_id, mock_id, student_id,
                                  status, submitted_at, created_at)
            VALUES (203, NULL, NULL, 103, 1, 'needs_review',
                    '2026-01-02 00:00:00', '2026-01-02 00:00:00');
    """
    )
    raw.commit()

    applied = _alembic(db, "upgrade", "head")
    assert applied.returncode == 0, applied.stderr

    work_ids = dict(raw.execute("SELECT id, work_id FROM submissions ORDER BY id").fetchall())
    assert work_ids == {201: 11, 202: 22, 203: 33}
    raw.close()


def test_a_submission_with_no_arm_aborts_the_migration(tmp_path) -> None:
    db = tmp_path / "stranded.db"
    at_0047 = _alembic(db, "upgrade", "0047")
    assert at_0047.returncode == 0, at_0047.stderr

    raw = sqlite3.connect(db)
    raw.executescript(
        """
        INSERT INTO organizations (id, name, created_at) VALUES (1, 'Org', '2026-01-01 00:00:00');
        INSERT INTO users (id, organization_id, name, role, password_hash, token_version, created_at)
            VALUES (1, 1, 'S', 'student', 'x', 0, '2026-01-01 00:00:00');
        -- All three arms NULL: nothing to take a parent from.
        INSERT INTO submissions (id, assignment_id, past_paper_id, mock_id, student_id,
                                  status, submitted_at, created_at)
            VALUES (301, NULL, NULL, NULL, 1, 'needs_review',
                    '2026-01-02 00:00:00', '2026-01-02 00:00:00');
    """
    )
    raw.commit()
    raw.close()

    blocked = _alembic(db, "upgrade", "head")
    assert blocked.returncode != 0
    # The count, not just the sentence: the migration has to say how many rows
    # are stranded or whoever reads the failed deploy log cannot size it.
    assert "1 submission(s) have no assignment, past paper or mock" in blocked.stderr


def test_downgrade_then_upgrade_rebackfills_real_rows(tmp_path) -> None:
    db = tmp_path / "updownup.db"
    at_0047 = _alembic(db, "upgrade", "0047")
    assert at_0047.returncode == 0, at_0047.stderr

    raw = sqlite3.connect(db)
    raw.executescript(
        _SCAFFOLD
        + """
        INSERT INTO assessable_work (id, organization_id, subject_id, kind, created_at)
            VALUES (44, 1, 1, 'homework', '2026-01-01 00:00:00');
        INSERT INTO assignments (id, group_id, title, status, created_at, work_id)
            VALUES (104, 1, 'Homework', 'published', '2026-01-01 00:00:00', 44);
        INSERT INTO submissions (id, assignment_id, past_paper_id, mock_id, student_id,
                                  status, submitted_at, created_at)
            VALUES (204, 104, NULL, NULL, 1, 'needs_review',
                    '2026-01-02 00:00:00', '2026-01-02 00:00:00');
    """
    )
    raw.commit()

    applied = _alembic(db, "upgrade", "head")
    assert applied.returncode == 0, applied.stderr
    assert raw.execute("SELECT work_id FROM submissions WHERE id = 204").fetchone()[0] == 44

    reverted = _alembic(db, "downgrade", "0047")
    assert reverted.returncode == 0, reverted.stderr
    with pytest.raises(sqlite3.OperationalError):
        raw.execute("SELECT work_id FROM submissions")

    reapplied = _alembic(db, "upgrade", "head")
    assert reapplied.returncode == 0, reapplied.stderr
    assert raw.execute("SELECT work_id FROM submissions WHERE id = 204").fetchone()[0] == 44
    raw.close()
