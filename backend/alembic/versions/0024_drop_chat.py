"""drop the student AI chat tables

Revision ID: 0024
Revises: 0023
Create Date: 2026-08-20

The student AI chat is deleted from the product (AV-57, reaffirmed by AV-100).
This drops the two tables 0005 created. The downgrade recreates them empty —
the conversations themselves are not recoverable from here, which is the
accepted cost of the decision.
"""

import sqlalchemy as sa

from alembic import op

revision = "0024"
down_revision = "0025"
# Reparented onto 0025: 0025_user_time_zone deployed first while
# this migration awaited review; chaining here keeps a single head (see §06).
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("chat_messages")
    op.drop_table("chat_conversations")


def downgrade() -> None:
    # Mirrors 0005 exactly, so up -> down -> up round-trips (DB-16).
    op.create_table(
        "chat_conversations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("student_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "chat_messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "conversation_id", sa.Integer(), sa.ForeignKey("chat_conversations.id"), nullable=False
        ),
        sa.Column(
            "role",
            sa.Enum("user", "assistant", name="chatrole", native_enum=False, length=12),
            nullable=False,
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
