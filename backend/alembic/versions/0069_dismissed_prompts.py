"""dismissed_prompts: a tutor's "Not now" on a home-page prompt

Revision ID: 0069
Revises: 0068
"""

import sqlalchemy as sa

from alembic import op

revision = "0069"
down_revision = "0068"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dismissed_prompts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey(
                "organizations.id", name="fk_dismissed_prompts_organization_id_organizations"
            ),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", name="fk_dismissed_prompts_user_id_users"),
            nullable=False,
        ),
        sa.Column("key", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "key", name="uq_dismissed_prompts_user_id_key"),
    )


def downgrade() -> None:
    op.drop_table("dismissed_prompts")
