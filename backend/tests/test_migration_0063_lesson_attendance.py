"""Migration 0063 (task 7.1): lesson mode/start time/origin, plan-slot start
time and cancellation, and the `lesson_attendance` table (`DB-12`)."""

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext

from app.models import Base
from tests.test_migration_0060_teaching_plans import STUBS, _load_migration, _shape
from tests.test_migration_0061_teaching_plan_draft_result import _load_0061
from tests.test_migration_0062_plan_slot_lesson import _load_0062

PATH = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0063_lesson_attendance.py"
LESSON_COLUMNS = {"mode", "start_time", "origin"}
SLOT_COLUMNS = {"start_time", "cancelled_at", "cancelled_by_id"}


def _load_0063():
    spec = importlib.util.spec_from_file_location("migration_0063", PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def chain():
    engine = sa.create_engine("sqlite://")
    with engine.connect() as conn:
        for table in (*STUBS, "lessons"):
            conn.execute(sa.text(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY)"))
        ctx = MigrationContext.configure(conn)
        modules = (_load_migration(), _load_0061(), _load_0062(), _load_0063())
        for module in modules:
            module.op = Operations(ctx)
            module.upgrade()
        conn.commit()
        yield conn, modules[-1]
    engine.dispose()


@pytest.fixture
def model_insp():
    engine = sa.create_engine("sqlite://")
    with engine.connect() as conn:
        Base.metadata.create_all(conn)
        yield sa.inspect(conn)
    engine.dispose()


def test_revision_metadata_chains_from_0062(chain):
    _, m63 = chain
    assert (m63.revision, m63.down_revision) == ("0063", "0062")


def test_lesson_attendance_matches_the_model(chain, model_insp):
    conn, _ = chain
    migrated = _shape(sa.inspect(conn), "lesson_attendance")
    assert migrated == _shape(model_insp, "lesson_attendance")
    assert migrated["uniques"] == {
        "uq_lesson_attendance_lesson_id_student_id": ["lesson_id", "student_id"]
    }
    assert set(migrated["indexes"]) == {
        "ix_lesson_attendance_student_id",
        "ix_lesson_attendance_organization_id",
    }
    assert migrated["fks"]["lesson_id"] == ("lessons", "CASCADE")


def test_added_columns_match_the_model(chain, model_insp):
    conn, _ = chain
    insp = sa.inspect(conn)
    for table, names in (("lessons", LESSON_COLUMNS), ("plan_slots", SLOT_COLUMNS)):
        migrated = _shape(insp, table)["columns"]
        modelled = _shape(model_insp, table)["columns"]
        for name in names:
            assert migrated[name] == modelled[name], (table, name)
    assert _shape(insp, "plan_slots")["fks"]["cancelled_by_id"] == ("users", None)
    assert _shape(model_insp, "plan_slots")["fks"]["cancelled_by_id"] == ("users", None)


def test_existing_lessons_backfill_to_in_person_and_tutor():
    engine = sa.create_engine("sqlite://")
    with engine.connect() as conn:
        for table in (*STUBS, "lessons"):
            conn.execute(sa.text(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY)"))
        conn.execute(sa.text("INSERT INTO lessons (id) VALUES (1)"))
        ctx = MigrationContext.configure(conn)
        for module in (_load_migration(), _load_0061(), _load_0062(), _load_0063()):
            module.op = Operations(ctx)
            module.upgrade()
        row = conn.execute(sa.text("SELECT mode, origin, start_time FROM lessons")).one()
    engine.dispose()
    assert tuple(row) == ("in_person", "tutor", None)


def test_downgrade_removes_the_table_and_columns_and_round_trips(chain):
    conn, m63 = chain
    m63.downgrade()
    conn.commit()
    insp = sa.inspect(conn)
    assert "lesson_attendance" not in insp.get_table_names()
    assert not LESSON_COLUMNS & {c["name"] for c in insp.get_columns("lessons")}
    slot_cols = {c["name"] for c in insp.get_columns("plan_slots")}
    assert not SLOT_COLUMNS & slot_cols
    assert "lesson_id" in slot_cols  # 0062's column survives
    m63.upgrade()
    conn.commit()
    insp = sa.inspect(conn)
    assert "lesson_attendance" in insp.get_table_names()
    assert {c["name"] for c in sa.inspect(conn).get_columns("plan_slots")} >= SLOT_COLUMNS
