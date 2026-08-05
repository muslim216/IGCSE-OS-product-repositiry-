"""assignments.classified_id becomes nullable (no-PDF assignments)

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-20

"""
import sqlalchemy as sa

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("assignments") as batch_op:
        batch_op.alter_column(
            "classified_id",
            existing_type=sa.Integer(),
            nullable=True,
        )


def downgrade() -> None:
    with op.batch_alter_table("assignments") as batch_op:
        batch_op.alter_column(
            "classified_id",
            existing_type=sa.Integer(),
            nullable=False,
        )
