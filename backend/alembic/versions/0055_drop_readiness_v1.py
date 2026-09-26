"""drop the readiness v1 tables

Task 5.3b (AV-78) deletes the v1 Readiness Engine. Since 5.3a every reader is
on v2 snapshots, so `topic_readiness`, `readiness_history` (v1's outputs) and
`tutor_preferences` (v1's weight sliders, superseded by `readiness_weights`)
have no reader and no writer left. Closes RISK-5.

Pending `recompute_readiness` jobs are deleted too: the handler is gone, so a
job queued by the previous release would otherwise fail with "No handler
registered" and sit in the failed-jobs list as noise. A running one is marked
failed rather than deleted: the old worker that claimed it can still write its
outcome over that row (it may itself fail, the tables being gone), and if that
worker died instead, a failed row is never reclaimed into a new worker with no
handler for it.

**The downgrade recreates the three tables empty.** Their rows are not
restored — v1's scores were derived from `evidence`, which this migration does
not touch, so a rolled-back release repopulates them the next time v1
recomputes a student. The deleted jobs are not restored either.

Revision ID: 0055
Revises: 0054
Create Date: 2026-09-26

"""

import sqlalchemy as sa

from alembic import op

revision = "0055"
down_revision = "0054"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DELETE FROM jobs WHERE type = 'recompute_readiness' AND status = 'pending'")
    op.execute(
        "UPDATE jobs SET status = 'failed', error = 'readiness v1 deleted (0055)' "
        "WHERE type = 'recompute_readiness' AND status = 'running'"
    )
    op.drop_table("topic_readiness")
    op.drop_table("readiness_history")
    op.drop_table("tutor_preferences")


def downgrade() -> None:
    # The shapes 0004 and 0009 created, empty.
    op.create_table(
        "topic_readiness",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("student_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("topic_id", sa.Integer(), sa.ForeignKey("topics.id"), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column(
            "confidence",
            sa.Enum(
                "none",
                "low",
                "medium",
                "high",
                name="readinessconfidence",
                native_enum=False,
                length=8,
            ),
            nullable=False,
        ),
        sa.Column("evidence_count", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("student_id", "topic_id"),
    )
    op.create_table(
        "readiness_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("student_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("subject_id", sa.Integer(), sa.ForeignKey("subjects.id"), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
    )
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
