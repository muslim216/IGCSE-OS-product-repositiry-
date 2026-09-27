"""chapter rows on factor_evaluations

Task 5.2 (AV-9, E7) rolls Topic Mastery up to chapters: each run writes one
`topic_mastery` row per chapter beside its per-topic rows, told apart by a new
nullable `chapter_id` (set only on those rows).

The foreign key is composite, `(subject_id, chapter_id)` → `chapters(subject_id,
id)`, like `topics` and `classifieds` in 0029 and 0034: a single-column key proves
only that the chapter exists, not that it belongs to the row's subject. MATCH
SIMPLE skips the check while `chapter_id` is NULL, which is every other row.

No index: every reader selects by `evaluation_run_id`, which is already indexed
(`DB-12` asks for one only where a reader filters on the column).

`batch_alter_table` with the naming convention from 0020 and an explicitly named
FK, per `DB-17`. Historical rows keep NULL — an old run simply has no chapter rows.

Revision ID: 0056
Revises: 0055
Create Date: 2026-09-28

"""

import sqlalchemy as sa

from alembic import op

revision = "0056"
down_revision = "0055"
branch_labels = None
depends_on = None

NAMING = {
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
}

FK_NAME = "fk_factor_evaluations_subject_id_chapter_id_chapters"


def upgrade() -> None:
    with op.batch_alter_table("factor_evaluations", naming_convention=NAMING) as batch:
        batch.add_column(sa.Column("chapter_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            FK_NAME, "chapters", ["subject_id", "chapter_id"], ["subject_id", "id"]
        )


def downgrade() -> None:
    with op.batch_alter_table("factor_evaluations", naming_convention=NAMING) as batch:
        batch.drop_constraint(FK_NAME, type_="foreignkey")
        batch.drop_column("chapter_id")
