"""Migration 0080 (T-076): `teaching_plan_papers` and `teaching_plans.revision_start_date`.

Runs on SQLite, which cannot prove Postgres behaviour; CI's up -> down -> up on
Postgres 16 is the check for that (`RISK-3`)."""

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext

from tests.test_migration_0060_teaching_plans import STUBS, _load_migration

PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "0080_plan_papers_and_revision_date.py"
)


def _load_0080():
    spec = importlib.util.spec_from_file_location("migration_0080", PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def world():
    engine = sa.create_engine("sqlite://")
    with engine.connect() as conn:
        for table in STUBS:
            conn.execute(sa.text(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY)"))
        ctx = MigrationContext.configure(conn)
        m60, m80 = _load_migration(), _load_0080()
        for module in (m60, m80):
            module.op = Operations(ctx)
        m60.upgrade()
        for gid, day in ((1, "2027-05-01"), (2, "2027-06-15")):
            conn.execute(
                sa.text(
                    "INSERT INTO teaching_plans (organization_id, group_id, status, exam_date, "
                    "lessons_per_week, lesson_minutes, created_at) VALUES "
                    f"(1, {gid}, 'draft', '{day}', 2, 60, CURRENT_TIMESTAMP)"
                )
            )
        conn.commit()
        yield conn, m80
    engine.dispose()


def _papers(conn):
    return conn.execute(
        sa.text("SELECT plan_id, name, exam_date, position FROM teaching_plan_papers ORDER BY 1")
    ).all()


def test_revision_metadata_chains_from_0079(world):
    _, m80 = world
    assert (m80.revision, m80.down_revision) == ("0080", "0079")


def test_every_existing_plan_gets_one_paper_named_exam_from_its_exam_date(world):
    conn, m80 = world
    m80.upgrade()
    assert [tuple(r) for r in _papers(conn)] == [
        (1, "Exam", "2027-05-01", 1),
        (2, "Exam", "2027-06-15", 1),
    ]
    cols = {c["name"]: c for c in sa.inspect(conn).get_columns("teaching_plans")}
    assert cols["revision_start_date"]["nullable"] is True
    assert conn.execute(
        sa.text("SELECT revision_start_date FROM teaching_plans")
    ).scalars().all() == [
        None,
        None,
    ]


def test_papers_are_unique_by_position_and_indexed_by_plan(world):
    conn, m80 = world
    m80.upgrade()
    insp = sa.inspect(conn)
    uniques = {
        u["name"]: u["column_names"] for u in insp.get_unique_constraints("teaching_plan_papers")
    }
    assert uniques["uq_teaching_plan_papers_plan_id_position"] == ["plan_id", "position"]
    assert "ix_teaching_plan_papers_plan_id" in {
        i["name"] for i in insp.get_indexes("teaching_plan_papers")
    }
    fk = insp.get_foreign_keys("teaching_plan_papers")[0]
    assert fk["options"]["ondelete"] == "CASCADE"


def test_downgrade_drops_both_and_upgrade_again_works(world):
    conn, m80 = world
    m80.upgrade()
    m80.downgrade()
    insp = sa.inspect(conn)
    assert "teaching_plan_papers" not in insp.get_table_names()
    assert "revision_start_date" not in {c["name"] for c in insp.get_columns("teaching_plans")}
    m80.upgrade()
    assert len(_papers(conn)) == 2


def test_the_migration_matches_the_model(world):
    from app.models import Base
    from tests.test_migration_0060_teaching_plans import _shape

    conn, m80 = world
    m80.upgrade()
    model_engine = sa.create_engine("sqlite://")
    with model_engine.connect() as model_conn:
        Base.metadata.create_all(model_conn)
        paper_model = _shape(sa.inspect(model_conn), "teaching_plan_papers")
        plan_model = _shape(sa.inspect(model_conn), "teaching_plans")
    model_engine.dispose()
    assert _shape(sa.inspect(conn), "teaching_plan_papers") == paper_model
    migrated = _shape(sa.inspect(conn), "teaching_plans")["columns"]["revision_start_date"]
    assert migrated == plan_model["columns"]["revision_start_date"]
