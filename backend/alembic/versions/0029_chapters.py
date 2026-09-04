"""Subject -> Chapter -> Topic: the chapter table and topic reparenting

Task 2.1 (AV-9, E1). A chapter is what the teaching plan schedules, what a
classified belongs to, and what carries a rolled-up readiness score. `E1` chose a
table over `Topic.parent_id` for exactly that reason: a parent topic is itself
markable, and a chapter is not. `Topic.parent_id` is left alone — it still means
"genuine sub-topic".

`topics.chapter_id` is **nullable**. Syllabus extraction stays flat until task
2.3, so a topic drafted today has no chapter to point at, and manufacturing one
would invent structure the tutor never approved (`PROD-2`).

**The backfill promotes, it does not move.** Each root topic (`parent_id IS
NULL`) gets a `chapters` row copying its code, title and weight, and the whole
subtree beneath it — the root row included — is pointed at that chapter. The root
`topics` rows are deliberately **kept**: `seed/demo.py` attaches evidence, lesson
topics and question topics to the first eight topics by code, which on the
Edexcel/Cambridge seeds includes roots like "1". Deleting them would cascade away
demo evidence to make the tree tidier. They go with the seeds themselves in task
2.2, where the whole subject is rebuilt.

No production data exists, so this migration is permitted to be destructive
(`E25`); it is written not to be anyway. Restore path if one is ever needed:
`pg_restore` the snapshot named in the PR, then `alembic downgrade 0028`.

`batch_alter_table` with the naming convention from 0020 and an explicitly named
FK, per `DB-17`: SQLite rebuilds a table on ALTER and refuses unnamed reflected
constraints. Both indexes are declared in `models/syllabus.py` too (`DB-12`).

Revision ID: 0029
Revises: 0028
Create Date: 2026-09-04

"""

import sqlalchemy as sa

from alembic import op

NAMING = {
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
}

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chapters",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("subject_id", sa.Integer(), sa.ForeignKey("subjects.id"), nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("weight", sa.Float(), nullable=False, server_default="1.0"),
        sa.UniqueConstraint("subject_id", "code"),
    )
    op.create_index("ix_chapters_subject_id_position", "chapters", ["subject_id", "position"])

    with op.batch_alter_table("topics", naming_convention=NAMING) as batch:
        batch.add_column(
            sa.Column(
                "chapter_id",
                sa.Integer(),
                sa.ForeignKey("chapters.id", name="fk_topics_chapter_id_chapters"),
                nullable=True,
            )
        )
    op.create_index("ix_topics_chapter_id", "topics", ["chapter_id"])

    promote_root_topics_to_chapters(op.get_bind())


# Takes the connection rather than reaching for `op.get_bind()` so the suite can
# run it directly (`tests/test_chapters.py`). The migration suite never runs a
# migration — conftest builds the schema from `Base.metadata` — so a backfill
# left unreachable from a test is a backfill nothing checks (`RISK-3`).
def promote_root_topics_to_chapters(conn: sa.engine.Connection) -> None:
    roots = conn.execute(
        sa.text(
            "SELECT id, subject_id, code, title, weight FROM topics "
            "WHERE parent_id IS NULL ORDER BY subject_id, id"
        )
    ).fetchall()

    position_in_subject: dict[int, int] = {}
    for root in roots:
        position_in_subject[root.subject_id] = position_in_subject.get(root.subject_id, 0) + 1
        chapter_id = conn.execute(
            sa.text(
                "INSERT INTO chapters (subject_id, code, title, position, weight) "
                "VALUES (:subject_id, :code, :title, :position, :weight) RETURNING id"
            ),
            {
                "subject_id": root.subject_id,
                "code": root.code,
                "title": root.title,
                "position": position_in_subject[root.subject_id],
                "weight": root.weight,
            },
        ).scalar_one()
        conn.execute(
            sa.text("UPDATE topics SET chapter_id = :chapter_id WHERE id = :id"),
            {"chapter_id": chapter_id, "id": root.id},
        )

    # ponytail: one UPDATE per level of the tree rather than a recursive CTE.
    # Portable across Postgres and SQLite with no dialect branch, and the deepest
    # syllabus in seed/syllabus/*.json is two levels, so this runs twice. If a
    # syllabus ever nests deeply enough for this to matter, swap in a recursive
    # CTE — the loop is bounded by tree depth, not row count, so it cannot run
    # away.
    while True:
        result = conn.execute(
            sa.text(
                "UPDATE topics SET chapter_id = "
                "(SELECT p.chapter_id FROM topics p WHERE p.id = topics.parent_id) "
                "WHERE chapter_id IS NULL AND parent_id IS NOT NULL "
                "AND (SELECT p.chapter_id FROM topics p WHERE p.id = topics.parent_id) "
                "IS NOT NULL"
            )
        )
        if not result.rowcount:
            break


def downgrade() -> None:
    op.drop_index("ix_topics_chapter_id", table_name="topics")
    with op.batch_alter_table("topics", naming_convention=NAMING) as batch:
        batch.drop_column("chapter_id")
    op.drop_index("ix_chapters_subject_id_position", table_name="chapters")
    op.drop_table("chapters")
