"""reports

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-19

"""
from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "reports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("student_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("subject_id", sa.Integer(), sa.ForeignKey("subjects.id"), nullable=True),
        sa.Column("generated_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("audience", sa.Enum("student", "tutor", "parent", name="reportaudience", native_enum=False, length=12), nullable=False),
        sa.Column("status", sa.Enum("generating", "ready", "failed", name="reportstatus", native_enum=False, length=12), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("reports")
