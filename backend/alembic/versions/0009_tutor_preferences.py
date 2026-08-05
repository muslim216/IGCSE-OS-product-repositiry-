"""tutor_preferences (readiness weight sliders)

Revision ID: 0009
Revises: 0008
Create Date: 2026-07-20

"""
import sqlalchemy as sa

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tutor_preferences",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tutor_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, unique=True),
        sa.Column("weight_mock", sa.Float(), nullable=False, server_default="1.5"),
        sa.Column("weight_homework", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("weight_quiz", sa.Float(), nullable=False, server_default="0.8"),
        sa.Column("weight_observation", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("half_life_days", sa.Float(), nullable=False, server_default="45.0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("tutor_preferences")
