"""Migration 0064 (task 7.3): Zoom/Meet connections, participants, import status,
and the lesson meeting columns (`DB-12`: declared in the model as well)."""

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
from tests.test_migration_0063_lesson_attendance import _load_0063

PATH = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0064_meeting_integrations.py"
TABLES = ("meeting_connections", "meeting_participants", "lesson_meeting_imports")
LESSON_COLUMNS = {"meeting_provider", "meeting_ref"}


def _load_0064():
    spec = importlib.util.spec_from_file_location("migration_0064", PATH)
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
        modules = (
            _load_migration(),
            _load_0061(),
            _load_0062(),
            _load_0063(),
            _load_0064(),
        )
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


def test_revision_metadata_chains_from_0063(chain):
    _, m64 = chain
    assert (m64.revision, m64.down_revision) == ("0064", "0063")


@pytest.mark.parametrize("table", TABLES)
def test_tables_match_the_models(chain, model_insp, table):
    conn, _ = chain
    assert _shape(sa.inspect(conn), table) == _shape(model_insp, table)


def test_lesson_children_cascade_and_an_import_is_unique_per_lesson(chain):
    """Stated outright, not just compared with the model: a lesson's participants
    and import row must go with the lesson in Postgres, and a lesson has at most
    one import row."""
    conn, _ = chain
    insp = sa.inspect(conn)
    for table in ("meeting_participants", "lesson_meeting_imports"):
        assert _shape(insp, table)["fks"]["lesson_id"] == ("lessons", "CASCADE"), table
    imports = _shape(insp, "lesson_meeting_imports")
    unique_on_lesson = [cols for cols in imports["uniques"].values() if cols == ["lesson_id"]] + [
        cols
        for cols, is_unique in imports["indexes"].values()
        if is_unique and cols == ["lesson_id"]
    ]
    assert unique_on_lesson, imports
    # The columns the import generation and the Zoom suggestion rely on exist.
    assert "attempt" in imports["columns"]
    assert "suggested_student_id" in _shape(insp, "meeting_participants")["columns"]


def test_connection_is_unique_per_tutor_and_provider(chain):
    conn, _ = chain
    shape = _shape(sa.inspect(conn), "meeting_connections")
    assert shape["uniques"] == {
        "uq_meeting_connections_tutor_id_provider": ["tutor_id", "provider"]
    }


def test_lesson_columns_match_the_model_and_are_nullable(chain, model_insp):
    conn, _ = chain
    migrated = _shape(sa.inspect(conn), "lessons")["columns"]
    modelled = _shape(model_insp, "lessons")["columns"]
    for name in LESSON_COLUMNS:
        assert migrated[name] == modelled[name]
        assert migrated[name][1] is True


def test_downgrade_removes_everything_and_round_trips(chain):
    conn, m64 = chain
    m64.downgrade()
    conn.commit()
    insp = sa.inspect(conn)
    assert not set(TABLES) & set(insp.get_table_names())
    assert not LESSON_COLUMNS & {c["name"] for c in insp.get_columns("lessons")}
    assert "lesson_attendance" in insp.get_table_names()  # 0063 survives
    m64.upgrade()
    conn.commit()
    insp = sa.inspect(conn)
    assert set(TABLES) <= set(insp.get_table_names())
    assert {c["name"] for c in insp.get_columns("lessons")} >= LESSON_COLUMNS
