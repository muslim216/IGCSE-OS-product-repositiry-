"""drop the consistency weight

The Readiness Engine stops scoring `consistency` (task 5.1, AV-30): homework
performance is marked accuracy only, and completion/punctuality no longer
feed any factor score. `readiness_weights.weight_consistency` is a tutor
setting for a factor the engine never computes again, so it is dropped.

`ReadinessFactor.consistency` itself stays in the Python enum — historical
`factor_evaluations` rows still carry it, and the column is a non-native
Enum with no CHECK constraint (DB-5), so removing the member would make
SQLAlchemy raise LookupError loading those rows. This migration touches only
`readiness_weights`; `factor_evaluations.factor` is untouched, and being a
non-native enum (DB-5) there is nothing server-side to alter there either
way.

Revision ID: 0054
Revises: 0053
Create Date: 2026-09-23

"""

import sqlalchemy as sa

from alembic import op

# Copied verbatim from 0051_mistake_categories.py — see DB-17.
NAMING = {
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
}

revision = "0054"
down_revision = "0053"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("readiness_weights", naming_convention=NAMING) as batch:
        batch.drop_column("weight_consistency")


def downgrade() -> None:
    # The tutor's old weight is not restored — the column comes back at its
    # original default, which is all 0016 ever guaranteed.
    with op.batch_alter_table("readiness_weights", naming_convention=NAMING) as batch:
        batch.add_column(
            sa.Column("weight_consistency", sa.Float(), nullable=False, server_default="1.0")
        )
