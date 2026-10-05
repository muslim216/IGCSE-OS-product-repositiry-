"""taught_before_topics + groups.taught_before_answered_at: "where are you up to?" (task 9.1b)

Revision ID: 0067
Revises: 0066
"""

import sqlalchemy as sa

from alembic import op

# Naming convention from 0020_past_papers.py: SQLite rebuilds the table on ALTER and
# refuses unnamed reflected constraints.
NAMING = {
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
}

revision = "0067"
down_revision = "0066"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "taught_before_topics",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey(
                "organizations.id", name="fk_taught_before_topics_organization_id_organizations"
            ),
            nullable=False,
        ),
        sa.Column(
            "group_id",
            sa.Integer(),
            sa.ForeignKey("groups.id", name="fk_taught_before_topics_group_id_groups"),
            nullable=False,
        ),
        sa.Column(
            "topic_id",
            sa.Integer(),
            sa.ForeignKey("topics.id", name="fk_taught_before_topics_topic_id_topics"),
            nullable=False,
        ),
        sa.Column(
            "created_by_id",
            sa.Integer(),
            sa.ForeignKey("users.id", name="fk_taught_before_topics_created_by_id_users"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("group_id", "topic_id", name="uq_taught_before_topics_group_topic"),
    )
    op.create_index("ix_taught_before_topics_group_id", "taught_before_topics", ["group_id"])
    with op.batch_alter_table("groups", naming_convention=NAMING) as batch:
        batch.add_column(
            sa.Column("taught_before_answered_at", sa.DateTime(timezone=True), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("groups", naming_convention=NAMING) as batch:
        batch.drop_column("taught_before_answered_at")
    op.drop_index("ix_taught_before_topics_group_id", table_name="taught_before_topics")
    op.drop_table("taught_before_topics")
