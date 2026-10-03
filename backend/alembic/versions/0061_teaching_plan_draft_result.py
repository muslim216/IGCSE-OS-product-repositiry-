"""teaching plan draft result

Task 6.3. `teaching_plans.draft_result`: what the last drafting run did (the
weights and their reasons, whether the AI was used or degraded, and a failure
the tutor can act on). Without it the outcome lives only in a log line, and an
all-defaulted AI answer is indistinguishable from an AI-weighted plan
(PROD-1, PROD-2).

Nullable generic JSON (DB-7); NULL means the plan has never been drafted
(DB-9). No backfill: no plan has been drafted yet.

An existing table is altered, so `batch_alter_table` with the naming
convention (DB-17).

Revision ID: 0061
Revises: 0060
Create Date: 2026-10-03

"""

import sqlalchemy as sa

from alembic import op

NAMING = {
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
}

revision = "0061"
down_revision = "0060"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("teaching_plans", naming_convention=NAMING) as batch:
        batch.add_column(sa.Column("draft_result", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("teaching_plans", naming_convention=NAMING) as batch:
        batch.drop_column("draft_result")
