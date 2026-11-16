"""The realistic-data CI check's helpers: the cell generator and the count comparison."""

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

from scripts.seed_awkward_rows import (
    awkward_string,
    checked_path,
    compare_counts,
    is_numbered_by_db,
    parse_markers,
    seed,
)


def test_max_variant_fills_the_declared_length_exactly():
    assert len(awkward_string(255, "max", 1)) == 255
    assert len(awkward_string(1, "max", 1)) == 1


def test_no_variant_exceeds_a_short_column():
    for variant in ("max", "unicode", "empty", "dupe_a", "dupe_b"):
        assert len(awkward_string(3, variant, 9)) <= 3


def test_unbounded_text_is_long_and_empty_is_empty():
    assert len(awkward_string(None, "max", 1)) >= 10_000
    assert awkward_string(50, "empty", 1) == ""


def test_dupe_pair_differs_only_by_case_and_whitespace():
    a, b = awkward_string(50, "dupe_a", 1), awkward_string(50, "dupe_b", 2)
    assert a != b
    assert a.lower() == b.strip().lower()


def test_unicode_variant_carries_arabic_and_emoji():
    text = awkward_string(100, "unicode", 1)
    assert "مرحبا" in text
    assert "🧪" in text


def test_compare_counts_fails_on_a_fall_and_allows_a_dropped_or_new_table():
    _, failures = compare_counts({"a": 5, "gone": 0}, {"a": 5, "new": 0})
    assert failures == []
    _, failures = compare_counts({"a": 5}, {"a": 4})
    assert failures == ["a: 5 -> 4"]


def test_populated_table_dropped_fails_unless_marked():
    _, failures = compare_counts({"a": 5, "e": 0}, {})
    assert failures == ["a: dropped with 5 rows"]
    assert compare_counts({"a": 5}, {}, may_drop={"a"})[1] == []
    assert compare_counts({"a": 5}, {"a": 1}, may_lose_rows={"a"})[1] == []


def test_markers_are_read_from_migration_text():
    rows, drops = parse_markers(
        ["# realistic-data: may-drop-rows foo\n", "x\n# realistic-data: may-drop-table bar"]
    )
    assert rows == {"foo"}
    assert drops == {"bar"}


def _link_schema() -> sa.MetaData:
    md = sa.MetaData()
    sa.Table(
        "p",
        md,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("status", sa.String(8), nullable=False),
    )
    sa.Table(
        "l",
        md,
        sa.Column("p_id", sa.ForeignKey("p.id"), primary_key=True),
        sa.Column("q_id", sa.ForeignKey("p.id"), primary_key=True),
    )
    return md


def test_only_a_lone_fk_free_integer_pk_is_left_to_the_database():
    md = _link_schema()
    assert is_numbered_by_db(md.tables["p"], md.tables["p"].c.id)
    assert not is_numbered_by_db(md.tables["l"], md.tables["l"].c.p_id)


async def test_seed_fills_link_tables_and_copies_short_enum_like_values():
    md = _link_schema()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(md.create_all)
        await conn.execute(md.tables["p"].insert().values(status="active"))
        _, _, per_table = await seed(conn, md, {})
        statuses = {r[0] for r in await conn.execute(sa.select(md.tables["p"].c.status))}
    await engine.dispose()
    assert statuses == {"active"}  # no junk in an enum-like column
    assert per_table["l"] > 0


def test_cli_paths_outside_the_allowed_directory_are_refused(tmp_path):
    inside = checked_path(str(tmp_path / "counts.json"), tmp_path)
    assert inside == (tmp_path / "counts.json").resolve()
    with pytest.raises(SystemExit):
        checked_path("../escape.json", tmp_path)
    with pytest.raises(SystemExit):
        checked_path("/etc/passwd", tmp_path)
