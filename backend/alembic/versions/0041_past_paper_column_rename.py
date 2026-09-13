"""Free the word "booklet": PastPaper's own file columns become paper_*

"Booklet" meant three different things in this codebase (a classified, a past
paper's own file, and an ad hoc marking-prompt field). The product owner has
settled that "booklet" will mean one thing only — a set of past papers — with
a new `booklets` table arriving in a later spec. This migration is the part of
that cleanup that touches storage: `PastPaper.booklet_path/booklet_name/
booklet_mime` become `paper_path/paper_name/paper_mime`, matching
`Mock.paper_path/paper_name/paper_mime` so the three work kinds (homework,
past paper, mock) agree on what to call their own question document.

Pure rename, no data loss — `batch_alter_table` on SQLite copies existing rows
across, so every past paper's uploaded file survives the rename untouched.

`batch_alter_table` with 0020's naming convention, per `DB-17` — SQLite
rebuilds `past_papers` to rename a column.

Revision ID: 0041
Revises: 0040
Create Date: 2026-09-13

"""

import sqlalchemy as sa

from alembic import op

NAMING = {
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
}

revision = "0041"
down_revision = "0040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("past_papers", naming_convention=NAMING) as batch:
        batch.alter_column(
            "booklet_path", new_column_name="paper_path", existing_type=sa.String(length=255)
        )
        batch.alter_column(
            "booklet_name", new_column_name="paper_name", existing_type=sa.String(length=255)
        )
        batch.alter_column(
            "booklet_mime", new_column_name="paper_mime", existing_type=sa.String(length=128)
        )


def downgrade() -> None:
    with op.batch_alter_table("past_papers", naming_convention=NAMING) as batch:
        batch.alter_column(
            "paper_path", new_column_name="booklet_path", existing_type=sa.String(length=255)
        )
        batch.alter_column(
            "paper_name", new_column_name="booklet_name", existing_type=sa.String(length=255)
        )
        batch.alter_column(
            "paper_mime", new_column_name="booklet_mime", existing_type=sa.String(length=128)
        )
