"""alembic/versions/0023_narratives.py — the append-only narratives table.

The migration's own docstring claims two properties worth locking in with a
real test rather than trusting the comment: the downgrade is a clean
drop_table (nothing holds an FK to `narratives`), and the migration was
"verified up -> down -> up". This runs the migration's own upgrade()/downgrade()
functions against a real (SQLite) connection via a bare Alembic Operations
context — no env.py, no other 22 revisions — since this migration's
create_table has no dependency on any column added by an earlier revision
beyond the three tables it declares foreign keys to.
"""

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext

MIGRATION_PATH = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0023_narratives.py"


def _load_migration():
    spec = importlib.util.spec_from_file_location("migration_0023_narratives", MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def migration():
    return _load_migration()


@pytest.fixture
def conn():
    """A bare sync connection with only the three parent tables the migration's
    foreign keys point at — organizations, groups, users — so create_table
    exercises real FK targets rather than dangling references."""
    engine = sa.create_engine("sqlite://")
    with engine.connect() as connection:
        for table in ("organizations", "groups", "users"):
            connection.execute(sa.text(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY)"))
        connection.commit()
        yield connection
    engine.dispose()


@pytest.fixture
def bound_migration(migration, conn):
    """Point the migration module's `op` proxy at an Operations instance bound to
    `conn`, so upgrade()/downgrade() run for real without alembic's env.py."""
    context = MigrationContext.configure(conn)
    migration.op = Operations(context)
    return migration


def test_revision_metadata_chains_from_0022(migration):
    assert migration.revision == "0023"
    assert migration.down_revision == "0022"
    assert migration.branch_labels is None
    assert migration.depends_on is None


def test_upgrade_creates_the_table_with_expected_columns(bound_migration, conn):
    bound_migration.upgrade()
    conn.commit()

    columns = {c["name"]: c for c in sa.inspect(conn).get_columns("narratives")}
    assert set(columns) == {
        "id",
        "organization_id",
        "audience",
        "group_id",
        "student_id",
        "text",
        "prompt_version",
        "model",
        "generated_at",
    }
    # The two polymorphic target FKs are nullable — exactly one is set per row,
    # selected by `audience`.
    assert columns["group_id"]["nullable"] is True
    assert columns["student_id"]["nullable"] is True
    # Everything else that identifies and dates a narrative is required.
    for required in ("organization_id", "audience", "text", "prompt_version", "model"):
        assert columns[required]["nullable"] is False, required


def test_upgrade_creates_the_three_named_indexes(bound_migration, conn):
    bound_migration.upgrade()
    conn.commit()

    indexes = {ix["name"]: ix["column_names"] for ix in sa.inspect(conn).get_indexes("narratives")}
    assert indexes["ix_narratives_org"] == ["organization_id"]
    assert indexes["ix_narratives_org_group"] == ["organization_id", "group_id", "id"]
    assert indexes["ix_narratives_org_student"] == ["organization_id", "student_id", "id"]


def test_upgrade_writes_and_reads_a_row(bound_migration, conn):
    """A smoke check that the created DDL actually accepts the shape the ORM
    model writes, not just that create_table did not raise."""
    bound_migration.upgrade()
    conn.commit()

    conn.execute(sa.text("INSERT INTO organizations (id) VALUES (1)"))
    conn.execute(sa.text("INSERT INTO groups (id) VALUES (1)"))
    conn.execute(
        sa.text(
            "INSERT INTO narratives "
            "(organization_id, audience, group_id, student_id, text, prompt_version, "
            "model, generated_at) "
            "VALUES (1, 'tutor_class', 1, NULL, 'stored text', 'v1', 'test-model', "
            "'2026-01-01 00:00:00+00:00')"
        )
    )
    conn.commit()
    row = conn.execute(sa.text("SELECT audience, text FROM narratives")).one()
    assert row.audience == "tutor_class"
    assert row.text == "stored text"


def test_downgrade_drops_the_indexes_and_the_table(bound_migration, conn):
    bound_migration.upgrade()
    conn.commit()
    bound_migration.downgrade()
    conn.commit()

    assert "narratives" not in sa.inspect(conn).get_table_names()


def test_up_down_up_roundtrip_does_not_raise(bound_migration, conn):
    """The migration's docstring claims this was verified; this keeps that claim
    checked rather than trusted."""
    bound_migration.upgrade()
    conn.commit()
    bound_migration.downgrade()
    conn.commit()
    bound_migration.upgrade()
    conn.commit()

    assert "narratives" in sa.inspect(conn).get_table_names()
    assert {ix["name"] for ix in sa.inspect(conn).get_indexes("narratives")} == {
        "ix_narratives_org",
        "ix_narratives_org_group",
        "ix_narratives_org_student",
    }


def test_downgrade_is_a_clean_drop_with_no_other_table_left_referencing_it(bound_migration, conn):
    """Nothing holds an FK to `narratives` (the migration's own claim): dropping
    it must not require dropping anything else first."""
    bound_migration.upgrade()
    conn.commit()
    bound_migration.downgrade()  # must not raise for want of a dependent drop
    conn.commit()
    remaining = set(sa.inspect(conn).get_table_names())
    assert remaining == {"organizations", "groups", "users"}
