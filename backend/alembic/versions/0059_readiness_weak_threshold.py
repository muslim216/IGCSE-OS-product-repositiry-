"""tutor-set weak-topic threshold on readiness_weights

Task 5.6. A weak topic is now deterministic (decision 10): a Topic Mastery row
with a score at or below this threshold. It lives on the same row as the
factor weights and resolves the same way — subject row, else account row, else
the built-in 60 (decision 8).

NOT NULL with a server default of 60, the value the one hard-coded constant
carried until now (reports and the v1 rule used it; v2's student surfaces used
the AI's picks, which are no longer read). `batch_alter_table` with the naming convention from 0020, per `DB-17`.

Revision ID: 0059
Revises: 0058
Create Date: 2026-09-29

"""

import sqlalchemy as sa

from alembic import op

revision = "0059"
down_revision = "0058"
branch_labels = None
depends_on = None

NAMING = {
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
}


def upgrade() -> None:
    with op.batch_alter_table("readiness_weights", naming_convention=NAMING) as batch:
        batch.add_column(
            sa.Column("weak_threshold", sa.Float(), nullable=False, server_default="60")
        )


def downgrade() -> None:
    with op.batch_alter_table("readiness_weights", naming_convention=NAMING) as batch:
        batch.drop_column("weak_threshold")
