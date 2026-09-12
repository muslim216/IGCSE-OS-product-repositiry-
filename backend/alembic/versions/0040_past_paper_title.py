"""A past paper's name comes from the document, not from the tutor

Task 3.5 (spec S3a). `PastPaper.title` is the full name read off the document
by extraction — "Cambridge IGCSE Physics 0625/41 Paper 4 Theory (Extended)
October/November 2026" — replacing the tutor's typed guess as what every site
displays (`PastPaper.display_title`, "Untitled paper" until extraction runs).

`session_label` and `paper_number` are AI-filled alongside `title` now, so
both become nullable — a freshly-uploaded paper has neither until its
extraction job runs. No unique constraint exists over either column or the
pair (checked against every migration touching `past_papers`), so nothing
downstream depends on them staying required.

`batch_alter_table` with 0020's naming convention, per `DB-17` — SQLite
rebuilds `past_papers` to alter a column's nullability. (The table itself was
created in `0016_readiness_v2_schema.py`; `0020_past_papers.py` only added
columns and the named tutor FK. Batch mode is required either way — noting the
provenance so nobody mis-cites 0020 as its origin later.)

Revision ID: 0040
Revises: 0039
Create Date: 2026-09-12

"""

import sqlalchemy as sa

from alembic import op

NAMING = {
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
}

revision = "0040"
down_revision = "0039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("past_papers", naming_convention=NAMING) as batch:
        batch.add_column(sa.Column("title", sa.String(length=255), nullable=True))
        batch.alter_column("session_label", existing_type=sa.String(length=64), nullable=True)
        batch.alter_column("paper_number", existing_type=sa.String(length=32), nullable=True)


def downgrade() -> None:
    with op.batch_alter_table("past_papers", naming_convention=NAMING) as batch:
        # THIS DOWNGRADE FAILS if any row has a null `session_label` or
        # `paper_number` — which is the normal state of every paper between
        # upload and its extraction job finishing, not an edge case. Reproduced:
        # a single such row gives `IntegrityError: NOT NULL constraint failed`,
        # and on SQLite the failed batch rebuild can strand a
        # `_alembic_tmp_past_papers` table behind it. Postgres has transactional
        # DDL and rolls back clean, so the production dialect fails in the safer
        # direction.
        #
        # Failing loudly is deliberate. The alternative is backfilling a session
        # label and paper number nobody read off the document, which is the
        # invented-data `PROD-2` forbids — going back down is not a reason to
        # start fabricating. An operator running this against a populated
        # database must delete or backfill the unextracted rows first.
        #
        # Note what does NOT catch this: CI's up -> down -> up runs on an empty
        # schema (`QA-11`), so it passes regardless. That blind spot is how this
        # project tests migrations generally, not something specific here.
        batch.alter_column("paper_number", existing_type=sa.String(length=32), nullable=False)
        batch.alter_column("session_label", existing_type=sa.String(length=64), nullable=False)
        batch.drop_column("title")
