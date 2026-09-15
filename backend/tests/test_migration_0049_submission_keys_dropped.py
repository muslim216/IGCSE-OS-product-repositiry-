"""The 0049 drop, run against rows that actually exist.

Same shape as `test_migration_0048_submission_work_id.py`: subprocess alembic
against a temp file-backed SQLite database, raw sqlite3 for the legacy rows.
The suite builds its schema from `Base.metadata` and CI's Postgres round-trip
runs against an empty database, so without this nothing anywhere runs 0049
over real submissions (`RISK-3`).
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


_SCAFFOLD = """
    INSERT INTO organizations (id, name, created_at) VALUES (1, 'Org', '2026-01-01 00:00:00');
    INSERT INTO subjects (id, organization_id, exam_board, code, name, level, grade_scale)
        VALUES (1, 1, 'Edexcel IGCSE', '4CH1', 'Chemistry', 'igcse', '9-1');
    INSERT INTO users (id, organization_id, name, role, password_hash, token_version, created_at)
        VALUES (1, 1, 'T', 'tutor', 'x', 0, '2026-01-01 00:00:00');
    INSERT INTO users (id, organization_id, name, role, password_hash, token_version, created_at)
        VALUES (2, 1, 'S', 'student', 'x', 0, '2026-01-01 00:00:00');
    INSERT INTO groups (id, organization_id, tutor_id, subject_id, name, created_at)
        VALUES (1, 1, 1, 1, 'Y11', '2026-01-01 00:00:00');
    INSERT INTO booklets (id, organization_id, subject_id, status, created_at)
        VALUES (1, 1, 1, 'applied', '2026-01-01 00:00:00');

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
"""


def _one_per_arm(student_id: int = 2) -> str:
    """One submission per arm, each carrying its own key and its parent."""
    return f"""
        INSERT INTO submissions (id, assignment_id, past_paper_id, mock_id, work_id,
                                  student_id, status, submitted_at, created_at)
            VALUES (201, 101, NULL, NULL, 11, {student_id}, 'needs_review',
                    '2026-01-02 00:00:00', '2026-01-02 00:00:00');
        INSERT INTO submissions (id, assignment_id, past_paper_id, mock_id, work_id,
                                  student_id, status, submitted_at, created_at)
            VALUES (202, NULL, 102, NULL, 22, {student_id}, 'needs_review',
                    '2026-01-02 00:00:00', '2026-01-02 00:00:00');
        INSERT INTO submissions (id, assignment_id, past_paper_id, mock_id, work_id,
                                  student_id, status, submitted_at, created_at)
            VALUES (203, NULL, NULL, 103, 33, {student_id}, 'needs_review',
                    '2026-01-02 00:00:00', '2026-01-02 00:00:00');
    """


def test_the_three_keys_go_and_the_work_pairing_becomes_unique(tmp_path) -> None:
    db = tmp_path / "drop.db"
    assert _alembic(db, "upgrade", "0048").returncode == 0

    raw = sqlite3.connect(db)
    raw.executescript(_SCAFFOLD + _one_per_arm())
    raw.commit()

    applied = _alembic(db, "upgrade", "head")
    assert applied.returncode == 0, applied.stderr

    columns = {row[1] for row in raw.execute("PRAGMA table_info(submissions)").fetchall()}
    assert columns.isdisjoint({"assignment_id", "past_paper_id", "mock_id"})
    assert "work_id" in columns
    # Every submission kept the parent it already pointed at.
    assert dict(raw.execute("SELECT id, work_id FROM submissions").fetchall()) == {
        201: 11,
        202: 22,
        203: 33,
    }

    # One attempt per student per piece of work is now a database rule, which
    # the three per-arm constraints could not express between them.
    with pytest.raises(sqlite3.IntegrityError):
        raw.execute(
            "INSERT INTO submissions (id, work_id, student_id, status, submitted_at, created_at) "
            "VALUES (204, 11, 2, 'needs_review', '2026-01-03 00:00:00', '2026-01-03 00:00:00')"
        )
    raw.rollback()
    raw.close()


def test_two_submissions_for_one_piece_of_work_abort_before_any_ddl(tmp_path) -> None:
    """The new constraint cannot be added over a duplicate, and finding that out
    from a failed ALTER mid-deploy names a constraint rather than the rows. It
    also has to refuse before the column drop, because SQLite commits the table
    rebuild an ALTER needs — refusing after would leave the table half-changed
    and break the re-run the message asks for."""
    db = tmp_path / "dupe.db"
    assert _alembic(db, "upgrade", "0048").returncode == 0

    raw = sqlite3.connect(db)
    raw.executescript(
        _SCAFFOLD
        + """
        -- Same student, same piece of work, through two different arms: legal
        -- under the three old constraints, which is the point.
        INSERT INTO submissions (id, assignment_id, past_paper_id, mock_id, work_id,
                                  student_id, status, submitted_at, created_at)
            VALUES (201, 101, NULL, NULL, 11, 2, 'needs_review',
                    '2026-01-02 00:00:00', '2026-01-02 00:00:00');
        INSERT INTO submissions (id, assignment_id, past_paper_id, mock_id, work_id,
                                  student_id, status, submitted_at, created_at)
            VALUES (202, NULL, 102, NULL, 11, 2, 'needs_review',
                    '2026-01-02 00:00:00', '2026-01-02 00:00:00');
    """
    )
    raw.commit()

    blocked = _alembic(db, "upgrade", "head")
    assert blocked.returncode != 0
    assert "1 (work_id, student_id) pair(s) have more than one submission" in blocked.stderr
    # Nothing was changed, so fixing the rows and re-running is a clean run.
    columns = {row[1] for row in raw.execute("PRAGMA table_info(submissions)").fetchall()}
    assert "assignment_id" in columns

    raw.execute("DELETE FROM submissions WHERE id = 202")
    raw.commit()
    recovered = _alembic(db, "upgrade", "head")
    assert recovered.returncode == 0, recovered.stderr
    raw.close()


def test_downgrade_puts_each_submission_back_on_its_own_arm(tmp_path) -> None:
    """Up -> down -> up on real rows (`DB-16`). The downgrade has to work out
    which arm each submission was on from `work_id` alone, and put the key back
    on that arm and no other."""
    db = tmp_path / "updownup.db"
    assert _alembic(db, "upgrade", "0048").returncode == 0

    raw = sqlite3.connect(db)
    raw.executescript(_SCAFFOLD + _one_per_arm())
    raw.commit()

    assert _alembic(db, "upgrade", "head").returncode == 0
    reverted = _alembic(db, "downgrade", "0048")
    assert reverted.returncode == 0, reverted.stderr

    rows = raw.execute(
        "SELECT id, assignment_id, past_paper_id, mock_id FROM submissions ORDER BY id"
    ).fetchall()
    assert rows == [(201, 101, None, None), (202, None, 102, None), (203, None, None, 103)]

    reapplied = _alembic(db, "upgrade", "head")
    assert reapplied.returncode == 0, reapplied.stderr
    assert dict(raw.execute("SELECT id, work_id FROM submissions").fetchall()) == {
        201: 11,
        202: 22,
        203: 33,
    }
    raw.close()
