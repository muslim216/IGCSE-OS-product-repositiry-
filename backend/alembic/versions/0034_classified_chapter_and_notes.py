"""Chapter-scoped classifieds, with chapter notes

Task 3.1 (`AV-20`, `AV-21`, `AV-23`). A classified is uploaded when the tutor
starts a chapter, and carries chapter-specific notes that are marking context
for the AI — the "chapter notes" layer of `AV-76`'s precedence, one step below
the official mark scheme and one above the subject's rules.

`chapter_id` is nullable and the foreign key is **composite** on
`(subject_id, chapter_id)`, exactly as `topics` is (migration 0029): a
single-column key would validate only that the chapter exists, leaving nothing
to stop a classified being filed under another subject's chapter — and a mark
then being made against notes written for a different syllabus. Both columns
sit in the constraint and `chapter_id` is nullable, so MATCH SIMPLE skips the
check entirely while it is NULL, which is every classified uploaded before
today.

`batch_alter_table` with 0020's naming convention, per `DB-17`; the composite
key is named explicitly because SQLite rebuilds the table on ALTER and refuses
unnamed reflected constraints.

Revision ID: 0034
Revises: 0033
Create Date: 2026-09-09

"""

import sqlalchemy as sa

from alembic import op

NAMING = {
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
}

revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("classifieds", naming_convention=NAMING) as batch:
        batch.add_column(sa.Column("chapter_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("notes", sa.Text(), nullable=True))
        batch.create_foreign_key(
            "fk_classifieds_subject_id_chapter_id_chapters",
            "chapters",
            ["subject_id", "chapter_id"],
            ["subject_id", "id"],
        )
    op.create_index("ix_classifieds_chapter_id", "classifieds", ["chapter_id"])


def downgrade() -> None:
    op.drop_index("ix_classifieds_chapter_id", table_name="classifieds")
    with op.batch_alter_table("classifieds", naming_convention=NAMING) as batch:
        # No explicit drop_constraint: batch mode rebuilds the table on SQLite,
        # and Postgres drops a constraint with the column it names. 0029's
        # downgrade of the identical key on `topics` does the same.
        batch.drop_column("notes")
        batch.drop_column("chapter_id")
