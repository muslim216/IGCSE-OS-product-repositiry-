"""submissions gain mistakes_analysed_at

`mistake_analysis()` (services/readiness_factors.py) could not tell "this
submission's questions were examined for mistakes and none were found" from
"nobody has looked yet" — an empty `mistakes` table reads as a clean record
either way. That is `PROD-2`: it scored a confident 100.0 for every student
with marked work, on one of seven weighted readiness factors. This column is
the marker the factor needs; nothing sets it yet (the tag_mistakes job lands
in 4.2), so the factor is correctly omitted for everyone until then — see
`services/readiness_v2.py`'s `_mistake_points_and_analysed`.

Revision ID: 0050
Revises: 0049
Create Date: 2026-09-18

"""

import sqlalchemy as sa

from alembic import op

# Copied verbatim from 0049 — see DB-17.
NAMING = {
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
}

revision = "0050"
down_revision = "0049"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("submissions", naming_convention=NAMING) as batch:
        batch.add_column(
            sa.Column("mistakes_analysed_at", sa.DateTime(timezone=True), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("submissions", naming_convention=NAMING) as batch:
        batch.drop_column("mistakes_analysed_at")
