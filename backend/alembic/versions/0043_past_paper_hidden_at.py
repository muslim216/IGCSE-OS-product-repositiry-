"""A tutor can take a paper off their own shelf without taking it from students

`past_papers.hidden_at` records when a tutor removed a paper from their list.
It is deliberately not a delete: students who can already see the paper keep
seeing it, and a delete would cascade through attempts, marks and the evidence
built on them.

Nullable with no backfill — every existing paper is visible, which is what NULL
already means.

Revision ID: 0043
Revises: 0042
Create Date: 2026-09-14

"""

import sqlalchemy as sa

from alembic import op

NAMING = {
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
}

revision = "0043"
down_revision = "0042"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # `batch_alter_table` with 0020's naming convention per `DB-17`: SQLite
    # rebuilds the table to add a column, and refuses to do so while
    # `past_papers` carries reflected constraints it cannot name.
    with op.batch_alter_table("past_papers", naming_convention=NAMING) as batch:
        batch.add_column(sa.Column("hidden_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("past_papers", naming_convention=NAMING) as batch:
        batch.drop_column("hidden_at")
