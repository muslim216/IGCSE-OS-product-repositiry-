"""Auto-marking trust model: mark review flags, override audit, remark requests

The AI now auto-finalizes marks it is confident about and flags the rest for
the tutor, so a QuestionMark needs to say which of those happened. Every tutor
change to a mark that already counted is audited, and a student can contest any
finalized mark exactly once.

SubmissionStatus / MarkConfidence gain values but need no DDL: both are stored
as VARCHAR (native_enum=False).

Revision ID: 0019
Revises: 0018
Create Date: 2026-07-24

"""
import sqlalchemy as sa

from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("question_marks") as batch:
        batch.add_column(
            sa.Column(
                "needs_review", sa.Boolean(), nullable=False, server_default=sa.false()
            )
        )
        batch.add_column(
            sa.Column(
                "auto_finalized", sa.Boolean(), nullable=False, server_default=sa.false()
            )
        )

    op.create_table(
        "mark_override_audit",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "question_mark_id",
            sa.Integer(),
            sa.ForeignKey("question_marks.id"),
            nullable=False,
        ),
        sa.Column("old_marks", sa.Integer(), nullable=True),
        sa.Column("new_marks", sa.Integer(), nullable=True),
        sa.Column("changed_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("reason", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_mark_override_audit_question_mark_id",
        "mark_override_audit",
        ["question_mark_id"],
    )

    op.create_table(
        "remark_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        # Unique: one request per question, ever. Enforces the cap in the
        # database, not just in the endpoint.
        sa.Column(
            "question_mark_id",
            sa.Integer(),
            sa.ForeignKey("question_marks.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("requested_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("remark_requests")
    op.drop_index("ix_mark_override_audit_question_mark_id", table_name="mark_override_audit")
    op.drop_table("mark_override_audit")
    with op.batch_alter_table("question_marks") as batch:
        batch.drop_column("auto_finalized")
        batch.drop_column("needs_review")
