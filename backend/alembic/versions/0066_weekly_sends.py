"""weekly_sends: the stored weekly send, one row per reader per week (task 8.2)

Revision ID: 0066
Revises: 0065
"""

import sqlalchemy as sa

from alembic import op

revision = "0066"
down_revision = "0065"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "weekly_sends",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey("organizations.id", name="fk_weekly_sends_organization_id_organizations"),
            nullable=False,
        ),
        sa.Column(
            "recipient_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", name="fk_weekly_sends_recipient_user_id_users"),
            nullable=False,
        ),
        sa.Column(
            "audience",
            sa.Enum(
                "tutor",
                "student",
                "parent",
                name="weeklysendaudience",
                native_enum=False,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("week_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("week_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("facts", sa.JSON(), nullable=False),
        sa.Column("paragraphs", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("recipient_user_id", "week_end", name="uq_weekly_sends_recipient_week"),
    )
    op.create_index("ix_weekly_sends_org_week", "weekly_sends", ["organization_id", "week_end"])


def downgrade() -> None:
    op.drop_index("ix_weekly_sends_org_week", table_name="weekly_sends")
    op.drop_table("weekly_sends")
