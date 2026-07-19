"""evidence, readiness, observations, assessments

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-19

"""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "evidence",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("student_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("topic_id", sa.Integer(), sa.ForeignKey("topics.id"), nullable=False),
        sa.Column("source_type", sa.Enum("homework", "quiz", "mock", "observation", name="evidencesource", native_enum=False, length=16), nullable=False),
        sa.Column("score_pct", sa.Float(), nullable=False),
        sa.Column("max_marks", sa.Integer(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_ref", sa.String(length=64), nullable=True),
        sa.Column("label", sa.String(length=255), nullable=True),
    )
    op.create_index("ix_evidence_student_topic", "evidence", ["student_id", "topic_id"])
    op.create_table(
        "topic_readiness",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("student_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("topic_id", sa.Integer(), sa.ForeignKey("topics.id"), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("confidence", sa.Enum("none", "low", "medium", "high", name="readinessconfidence", native_enum=False, length=8), nullable=False),
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
        "tutor_observations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tutor_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("student_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("topic_id", sa.Integer(), sa.ForeignKey("topics.id"), nullable=True),
        sa.Column("comment", sa.Text(), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "assessments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tutor_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("subject_id", sa.Integer(), sa.ForeignKey("subjects.id"), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("type", sa.Enum("mock", "test", name="assessmenttype", native_enum=False, length=8), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "assessment_scores",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("assessment_id", sa.Integer(), sa.ForeignKey("assessments.id"), nullable=False),
        sa.Column("student_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("topic_id", sa.Integer(), sa.ForeignKey("topics.id"), nullable=True),
        sa.Column("marks", sa.Integer(), nullable=False),
        sa.Column("max_marks", sa.Integer(), nullable=False),
    )


def downgrade() -> None:
    for table in (
        "assessment_scores",
        "assessments",
        "tutor_observations",
        "readiness_history",
        "topic_readiness",
    ):
        op.drop_table(table)
    op.drop_index("ix_evidence_student_topic", table_name="evidence")
    op.drop_table("evidence")
