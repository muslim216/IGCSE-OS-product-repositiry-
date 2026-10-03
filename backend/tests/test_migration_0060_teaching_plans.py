"""alembic/versions/0060_teaching_plans.py — the teaching plan tables.

Runs the migration's own upgrade()/downgrade() against bare SQLite. The suite's
schema is built from Base.metadata and production runs the migration, so a
constraint present in one and missing from the other is invisible to every other
test (`RISK-3`). The parity test at the bottom is what closes that gap.
"""

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext

from app.models import Base

MIGRATION_PATH = (
    Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0060_teaching_plans.py"
)
TABLES = ("teaching_plans", "plan_slots", "plan_breaks")
STUBS = ("organizations", "groups", "users", "chapters")


def _load_migration():
    spec = importlib.util.spec_from_file_location("migration_0060_teaching_plans", MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def conn():
    """A bare connection with only the parent tables the FKs point at. SQLite
    enforces CHECK and UNIQUE but not foreign keys, so inserts below use ids
    that need not exist."""
    engine = sa.create_engine("sqlite://")
    with engine.connect() as connection:
        for table in STUBS:
            connection.execute(sa.text(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY)"))
        connection.commit()
        yield connection
    engine.dispose()


@pytest.fixture
def migration(conn):
    module = _load_migration()
    module.op = Operations(MigrationContext.configure(conn))
    return module


@pytest.fixture
def upgraded(migration, conn):
    migration.upgrade()
    conn.commit()
    return conn


def _insert_plan(conn, **overrides):
    values = {
        "organization_id": 1,
        "group_id": 1,
        "status": "draft",
        "exam_date": "2027-05-01",
        "lessons_per_week": 2,
        "lesson_minutes": 60,
        "past_paper_start_date": None,
        "accepted_at": None,
        "accepted_by_id": None,
        "created_at": "2026-10-01 00:00:00",
    }
    values.update(overrides)
    cols = ", ".join(values)
    params = ", ".join(f":{k}" for k in values)
    conn.execute(sa.text(f"INSERT INTO teaching_plans ({cols}) VALUES ({params})"), values)  # noqa: S608


def test_revision_metadata_chains_from_0059(migration):
    assert migration.revision == "0060"
    assert migration.down_revision == "0059"
    assert migration.branch_labels is None
    assert migration.depends_on is None


EXPECTED_COLUMNS = {
    "teaching_plans": {
        "id": False,
        "organization_id": False,
        "group_id": False,
        "status": False,
        "exam_date": False,
        "lessons_per_week": False,
        "lesson_minutes": False,
        "past_paper_start_date": True,
        "accepted_at": True,
        "accepted_by_id": True,
        "created_at": False,
    },
    "plan_slots": {
        "id": False,
        "plan_id": False,
        "chapter_id": False,
        "scheduled_date": False,
        "sequence": False,
        "provenance": False,
        "created_at": False,
    },
    "plan_breaks": {
        "id": False,
        "plan_id": False,
        "start_date": False,
        "end_date": False,
        "label": False,
        "created_at": False,
    },
}


@pytest.mark.parametrize("table", TABLES)
def test_upgrade_creates_tables_with_expected_columns(upgraded, table):
    columns = {c["name"]: c["nullable"] for c in sa.inspect(upgraded).get_columns(table)}
    assert columns == EXPECTED_COLUMNS[table]


def test_upgrade_creates_named_indexes_and_unique_constraint(upgraded):
    insp = sa.inspect(upgraded)
    plan_ix = {ix["name"]: ix["column_names"] for ix in insp.get_indexes("teaching_plans")}
    assert plan_ix["ix_teaching_plans_organization_id"] == ["organization_id"]
    slot_ix = {ix["name"]: ix["column_names"] for ix in insp.get_indexes("plan_slots")}
    assert slot_ix == {
        "ix_plan_slots_plan_id_sequence": ["plan_id", "sequence"],
        "ix_plan_slots_chapter_id": ["chapter_id"],
    }
    # The sequence index is deliberately not unique.
    assert not any(ix["unique"] for ix in insp.get_indexes("plan_slots"))
    break_ix = {ix["name"]: ix["column_names"] for ix in insp.get_indexes("plan_breaks")}
    assert break_ix == {"ix_plan_breaks_plan_id": ["plan_id"]}
    uniques = {u["name"]: u["column_names"] for u in insp.get_unique_constraints("teaching_plans")}
    assert uniques == {"uq_teaching_plans_group_id_status": ["group_id", "status"]}


@pytest.mark.parametrize(
    "overrides",
    [
        {"lessons_per_week": 0},
        {"lesson_minutes": 0},
        {"exam_date": "2027-05-01", "past_paper_start_date": "2027-05-02"},
        {"status": "accepted"},
        {"status": "accepted", "accepted_at": "2026-10-01 00:00:00"},
        {"status": "accepted", "accepted_by_id": 1},
    ],
    ids=[
        "lessons_per_week_zero",
        "lesson_minutes_zero",
        "past_papers_after_exam",
        "accepted_without_acceptor",
        "accepted_without_by",
        "accepted_without_at",
    ],
)
def test_plan_checks_live_in_the_migration_ddl(upgraded, overrides):
    with pytest.raises(sa.exc.IntegrityError):
        _insert_plan(upgraded, **overrides)
    upgraded.rollback()


@pytest.mark.parametrize(
    "overrides",
    [
        {"past_paper_start_date": None},
        {"past_paper_start_date": "2027-05-01"},
        {"status": "accepted", "accepted_at": "2026-10-01 00:00:00", "accepted_by_id": 1},
    ],
    ids=["null_past_paper_start", "past_papers_on_exam_day", "accepted_with_acceptor"],
)
def test_plan_checks_accept_valid_rows(upgraded, overrides):
    _insert_plan(upgraded, **overrides)
    upgraded.commit()


def test_break_end_before_start_rejected_and_equal_accepted(upgraded):
    sql = sa.text(
        "INSERT INTO plan_breaks (plan_id, start_date, end_date, label, created_at) "
        "VALUES (1, :s, :e, 'Half term', '2026-10-01 00:00:00')"
    )
    upgraded.execute(sql, {"s": "2026-10-20", "e": "2026-10-20"})
    upgraded.commit()
    with pytest.raises(sa.exc.IntegrityError):
        upgraded.execute(sql, {"s": "2026-10-21", "e": "2026-10-20"})
    upgraded.rollback()


def test_second_draft_rejected_but_draft_plus_accepted_allowed(upgraded):
    _insert_plan(upgraded, status="draft")
    upgraded.commit()
    with pytest.raises(sa.exc.IntegrityError):
        _insert_plan(upgraded, status="draft")
    upgraded.rollback()
    _insert_plan(upgraded, status="accepted", accepted_at="2026-10-01 00:00:00", accepted_by_id=1)
    upgraded.commit()


def test_downgrade_removes_all_three_tables(upgraded, migration):
    migration.downgrade()
    upgraded.commit()
    assert not set(TABLES) & set(sa.inspect(upgraded).get_table_names())


def test_up_down_up_roundtrip_leaves_tables_present(upgraded, migration):
    migration.downgrade()
    upgraded.commit()
    migration.upgrade()
    upgraded.commit()
    assert set(TABLES) <= set(sa.inspect(upgraded).get_table_names())


def test_downgrade_warns_with_row_count(upgraded, migration, capsys):
    _insert_plan(upgraded)
    upgraded.commit()
    migration.downgrade()
    assert "WARNING: dropping 1 row(s) of teaching_plans" in capsys.readouterr().out


def _shape(insp, table):
    fks = {
        fk["constrained_columns"][0]: (fk["referred_table"], (fk["options"] or {}).get("ondelete"))
        for fk in insp.get_foreign_keys(table)
    }
    return {
        # Type as well as nullability: a VARCHAR(16) in one and VARCHAR(20) in
        # the other truncates on Postgres and passes on SQLite.
        "columns": {c["name"]: (str(c["type"]), c["nullable"]) for c in insp.get_columns(table)},
        "indexes": {
            ix["name"]: (ix["column_names"], bool(ix["unique"])) for ix in insp.get_indexes(table)
        },
        "uniques": {u["name"]: u["column_names"] for u in insp.get_unique_constraints(table)},
        # The expression, not just the name: `>= 1` against `> 1` is drift too.
        "checks": {
            c["name"]: " ".join(c["sqltext"].split()) for c in insp.get_check_constraints(table)
        },
        "fks": fks,
    }


EXPECTED_CHECKS = {
    "teaching_plans": {
        "ck_teaching_plans_lessons_per_week_positive",
        "ck_teaching_plans_lesson_minutes_positive",
        "ck_teaching_plans_past_papers_before_exam",
        "ck_teaching_plans_accepted_has_acceptor",
    },
    "plan_slots": set(),
    "plan_breaks": {"ck_plan_breaks_end_not_before_start"},
}

# Pinned, not just compared: a model and migration that drift together (both
# CASCADE on chapter_id) would agree and still destroy hand-edited slots.
EXPECTED_FKS = {
    "teaching_plans": {
        "organization_id": ("organizations", None),
        "group_id": ("groups", "CASCADE"),
        "accepted_by_id": ("users", None),
    },
    "plan_slots": {
        "plan_id": ("teaching_plans", "CASCADE"),
        "chapter_id": ("chapters", "RESTRICT"),
    },
    "plan_breaks": {"plan_id": ("teaching_plans", "CASCADE")},
}


@pytest.mark.parametrize("table", TABLES)
def test_migration_matches_model_metadata(upgraded, table):
    """RISK-3: the test schema comes from the models, production from this
    migration. Any drift between them is a bug the rest of the suite cannot see."""
    model_engine = sa.create_engine("sqlite://")
    with model_engine.connect() as model_conn:
        # The whole model schema, so the plan tables' FKs point at real parents
        # here and at the stubs on the migration side.
        Base.metadata.create_all(model_conn)
        model_shape = _shape(sa.inspect(model_conn), table)
    model_engine.dispose()
    migration_shape = _shape(sa.inspect(upgraded), table)
    # Columns added by later revisions (0061's draft_result) are in the model but
    # not in this revision's DDL; test_migration_0061 holds the full-chain parity.
    model_shape["columns"].pop("draft_result", None)

    assert migration_shape["columns"] == model_shape["columns"]
    assert migration_shape["indexes"] == model_shape["indexes"]
    assert migration_shape["uniques"] == model_shape["uniques"]
    assert migration_shape["checks"] == model_shape["checks"]
    # Named here too, so two schemas that both lost a check do not agree.
    assert set(migration_shape["checks"]) == EXPECTED_CHECKS[table]
    # Parent tables differ (stubs vs real) in nothing that matters here: compare
    # the referred table and ondelete per constrained column.
    assert migration_shape["fks"] == model_shape["fks"] == EXPECTED_FKS[table]
