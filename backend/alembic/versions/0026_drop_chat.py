"""drop the student AI chat tables

Task 0.3 (AV-57, AV-100) deletes the student AI chat surface. Avora is not an
AI tutor: the platform is the product, and a chat window that answers a
student's questions is the one surface that competes with the tutor rather
than serving them.

The router, service, model and screen went with it, so these two tables have
no reader left. **This drops stored conversations irrecoverably** — that is
deliberate and was confirmed with the product manager, but it is the reason
this migration is worth reading before running it anywhere with real users.

The `chat` member of `AiFeature` is deliberately NOT removed: every call the
surface ever made is still a row in `ai_usage_events`, and that spend has to
stay readable. See the comment on the enum.

Revision ID: 0026
Revises: 0025
Create Date: 2026-08-24

"""

import sqlalchemy as sa
from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Messages first: they carry the FK to conversations.
    op.drop_table("chat_messages")
    op.drop_table("chat_conversations")


def downgrade() -> None:
    # Recreates the tables exactly as 0005_chat built them, so up → down → up
    # is clean (DB-16). The rows themselves are gone for good — a downgrade
    # restores the schema, never the conversations.
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
