"""Migration 0061 (task 6.3): `teaching_plans.draft_result`."""

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext

from app.models import Base
from tests.test_migration_0060_teaching_plans import STUBS, _load_migration, _shape

PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "0061_teaching_plan_draft_result.py"
)


def _load_0061():
    spec = importlib.util.spec_from_file_location("migration_0061", PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def chain():
    engine = sa.create_engine("sqlite://")
    with engine.connect() as conn:
        for table in STUBS:
            conn.execute(sa.text(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY)"))
        ctx = MigrationContext.configure(conn)
        m60, m61 = _load_migration(), _load_0061()
        for module in (m60, m61):
            module.op = Operations(ctx)
        m60.upgrade()
        m61.upgrade()
        conn.commit()
        yield conn, m60, m61
    engine.dispose()


def test_revision_metadata_chains_from_0060(chain):
    _, _, m61 = chain
    assert (m61.revision, m61.down_revision) == ("0061", "0060")


def test_the_column_is_nullable_json(chain):
    conn, _, _ = chain
    col = {c["name"]: c for c in sa.inspect(conn).get_columns("teaching_plans")}["draft_result"]
    assert col["nullable"] is True
    assert "JSON" in str(col["type"]).upper()


def test_full_chain_matches_the_model_for_every_plan_table(chain):
    conn, _, _ = chain
    model_engine = sa.create_engine("sqlite://")
    with model_engine.connect() as model_conn:
        Base.metadata.create_all(model_conn)
        for table in ("teaching_plans", "plan_slots", "plan_breaks"):
            assert _shape(sa.inspect(conn), table) == _shape(sa.inspect(model_conn), table)
    model_engine.dispose()


def test_downgrade_drops_only_the_column_and_keeps_rows(chain):
    conn, _, m61 = chain
    conn.execute(
        sa.text(
            "INSERT INTO teaching_plans (organization_id, group_id, status, exam_date,"
            " lessons_per_week, lesson_minutes, created_at, draft_result)"
            " VALUES (1, 1, 'draft', '2027-05-01', 2, 60, '2026-10-01', '{\"status\": \"drafted\"}')"
        )
    )
    m61.downgrade()
    conn.commit()
    names = {c["name"] for c in sa.inspect(conn).get_columns("teaching_plans")}
    assert "draft_result" not in names
    assert conn.execute(sa.text("SELECT count(*) FROM teaching_plans")).scalar() == 1
    m61.upgrade()
    conn.commit()
    assert "draft_result" in {c["name"] for c in sa.inspect(conn).get_columns("teaching_plans")}
