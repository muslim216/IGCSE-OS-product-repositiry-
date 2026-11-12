"""THROWAWAY (T-051 proof by breaking): NOT NULL column with no default on a populated table.

Must fail on realistic data and pass on an empty database. Removed in the next commit.
"""

import sqlalchemy as sa
from alembic import op

revision = "0080"
down_revision = "0079"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("t051_proof", sa.String(10), nullable=False))


def downgrade() -> None:
    op.drop_column("users", "t051_proof")
