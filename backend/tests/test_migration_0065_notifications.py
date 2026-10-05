"""Migration 0065 (task 8.1): runs up and down on SQLite, and its tables match the
models column for column (`DB-12`)."""

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext

from app.models import Base

PATH = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0065_notifications.py"
TABLES = ("contact_points", "notification_preferences", "notifications")
ORG_COLUMNS = {"weekly_send_weekday", "weekly_send_hour", "ai_language"}


def _load():
    spec = importlib.util.spec_from_file_location("migration_0065", PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def migrated():
    engine = sa.create_engine("sqlite://")
    with engine.connect() as conn:
        conn.execute(sa.text("CREATE TABLE users (id INTEGER PRIMARY KEY)"))
        conn.execute(sa.text("CREATE TABLE organizations (id INTEGER PRIMARY KEY, name TEXT)"))
        conn.execute(sa.text("INSERT INTO organizations (id, name) VALUES (1, 'existing')"))
        module = _load()
        module.op = Operations(MigrationContext.configure(conn))
        module.upgrade()
        conn.commit()
        yield conn, module
    engine.dispose()


def test_existing_organizations_get_the_defaults(migrated):
    conn, _ = migrated
    row = conn.execute(
        sa.text("SELECT weekly_send_weekday, weekly_send_hour, ai_language FROM organizations")
    ).one()
    assert tuple(row) == (6, 17, "en")


def test_tables_match_the_models(migrated):
    conn, _ = migrated
    insp = sa.inspect(conn)
    model_conn = sa.create_engine("sqlite://").connect()
    Base.metadata.create_all(model_conn)
    model_insp = sa.inspect(model_conn)
    for table in TABLES:
        assert {c["name"] for c in insp.get_columns(table)} == {
            c["name"] for c in model_insp.get_columns(table)
        }, table
        assert {i["name"] for i in insp.get_indexes(table)} == {
            i["name"] for i in model_insp.get_indexes(table)
        }, table
    assert {c["name"] for c in insp.get_columns("organizations")} >= ORG_COLUMNS
    model_conn.close()


def test_downgrade_removes_everything_it_added(migrated):
    conn, module = migrated
    module.downgrade()
    insp = sa.inspect(conn)
    assert not set(TABLES) & set(insp.get_table_names())
    assert not ORG_COLUMNS & {c["name"] for c in insp.get_columns("organizations")}
