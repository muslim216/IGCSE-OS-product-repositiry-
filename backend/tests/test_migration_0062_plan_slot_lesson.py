"""Migration 0062 (task 6.5): `plan_slots.lesson_id`."""

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext

from app.models import Base
from tests.test_migration_0060_teaching_plans import STUBS, _load_migration, _shape
from tests.test_migration_0061_teaching_plan_draft_result import _load_0061

PATH = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0062_plan_slot_lesson.py"


def _load_0062():
    spec = importlib.util.spec_from_file_location("migration_0062", PATH)
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
        modules = (_load_migration(), _load_0061(), _load_0062())
        for module in modules:
            module.op = Operations(ctx)
            module.upgrade()
        conn.commit()
        yield conn, modules[-1]
    engine.dispose()


def test_revision_metadata_chains_from_0061(chain):
    _, m62 = chain
    assert (m62.revision, m62.down_revision) == ("0062", "0061")


def test_the_column_is_a_nullable_integer_with_a_set_null_fk_and_unique(chain):
    conn, _ = chain
    insp = sa.inspect(conn)
    col = {c["name"]: c for c in insp.get_columns("plan_slots")}["lesson_id"]
    assert col["nullable"] is True
    fks = {fk["constrained_columns"][0]: fk for fk in insp.get_foreign_keys("plan_slots")}
    assert fks["lesson_id"]["referred_table"] == "lessons"
    assert fks["lesson_id"]["options"]["ondelete"] == "SET NULL"
    assert fks["lesson_id"]["name"] == "fk_plan_slots_lesson_id_lessons"
    uniques = {u["name"]: u["column_names"] for u in insp.get_unique_constraints("plan_slots")}
    assert uniques["uq_plan_slots_lesson_id"] == ["lesson_id"]


def test_full_chain_matches_the_model_for_every_plan_table(chain):
    conn, _ = chain
    model_engine = sa.create_engine("sqlite://")
    with model_engine.connect() as model_conn:
        Base.metadata.create_all(model_conn)
        for table in ("teaching_plans", "plan_slots", "plan_breaks"):
            assert _shape(sa.inspect(conn), table) == _shape(sa.inspect(model_conn), table)
    model_engine.dispose()


def test_downgrade_drops_only_the_link_and_keeps_rows(chain):
    conn, m62 = chain
    conn.execute(
        sa.text(
            "INSERT INTO plan_slots (plan_id, chapter_id, scheduled_date, sequence, provenance,"
            " created_at, lesson_id) VALUES (1, 1, '2027-02-02', 1, 'confirmed', '2026-10-01', 7)"
        )
    )
    m62.downgrade()
    conn.commit()
    insp = sa.inspect(conn)
    assert "lesson_id" not in {c["name"] for c in insp.get_columns("plan_slots")}
    assert "uq_plan_slots_lesson_id" not in {
        u["name"] for u in insp.get_unique_constraints("plan_slots")
    }
    row = conn.execute(sa.text("SELECT plan_id, provenance FROM plan_slots")).all()
    assert [tuple(r) for r in row] == [(1, "confirmed")]
    m62.upgrade()
    conn.commit()
    insp = sa.inspect(conn)
    assert "lesson_id" in {c["name"] for c in insp.get_columns("plan_slots")}
    # After down -> up the constraints are back, not merely the column.
    fks = {fk["constrained_columns"][0]: fk for fk in insp.get_foreign_keys("plan_slots")}
    assert fks["lesson_id"]["referred_table"] == "lessons"
    assert fks["lesson_id"]["options"]["ondelete"] == "SET NULL"
    uniques = {u["name"]: u["column_names"] for u in insp.get_unique_constraints("plan_slots")}
    assert uniques["uq_plan_slots_lesson_id"] == ["lesson_id"]
    # The row survived the round trip; the link itself did not (the column was dropped).
    row = conn.execute(sa.text("SELECT plan_id, provenance, lesson_id FROM plan_slots")).all()
    assert [tuple(r) for r in row] == [(1, "confirmed", None)]
