"""How many pages a booklet actually has

Counted once when the AI reads the document, and checked at approval: a page
range that runs past the end is then refused before anything is cut, rather
than failing inside the split job and leaving a half-cut booklet that cannot
be edited.

Nullable with no backfill — counting the pages of an existing booklet means
parsing its PDF, and null already means "not counted", which the check skips.

Revision ID: 0044
Revises: 0043
Create Date: 2026-09-14

"""

import sqlalchemy as sa

from alembic import op

NAMING = {
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
}

revision = "0044"
down_revision = "0043"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("booklets", naming_convention=NAMING) as batch:
        batch.add_column(sa.Column("page_count", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("booklets", naming_convention=NAMING) as batch:
        batch.drop_column("page_count")
