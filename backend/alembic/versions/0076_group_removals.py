"""group removals: a removed student stays removed

A tutor removing a student from a class is recorded so the class's join link
cannot let them straight back in (audit GH-1). One row per (class, student); a
tutor adding the student back deletes it.

Revision ID: 0076
Revises: 0075
"""

import sqlalchemy as sa

from alembic import op

revision = "0076"
down_revision = "0075"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "group_removals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False
        ),
        sa.Column("group_id", sa.Integer(), sa.ForeignKey("groups.id"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("group_id", "user_id", name="uq_group_removals_group_user"),
    )


def downgrade() -> None:
    op.drop_table("group_removals")
