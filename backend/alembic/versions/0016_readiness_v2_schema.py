"""Readiness Engine v2 schema — Phase 1 (schema & models)

Adds question difficulty/unseen, mistakes, past papers, org-level grade
boundaries, readiness_weights (supersedes tutor_preferences), and the
factor_evaluations / readiness_snapshots append-only tables (supersede
topic_readiness / readiness_history). The v1 engine and its tables are left
untouched and fully functional — nothing reads from these new tables yet.

Revision ID: 0016
Revises: 0015
Create Date: 2026-07-23

"""
from alembic import op
import sqlalchemy as sa

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("assignment_questions") as batch_op:
        batch_op.add_column(
            sa.Column(
                "difficulty",
                sa.Enum("easy", "medium", "hard", name="questiondifficulty", native_enum=False, length=8),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column("unseen", sa.Boolean(), nullable=False, server_default=sa.false())
        )

    op.create_table(
        "mistakes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("student_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "question_mark_id", sa.Integer(), sa.ForeignKey("question_marks.id"), nullable=False
        ),
        sa.Column("topic_id", sa.Integer(), sa.ForeignKey("topics.id"), nullable=True),
        sa.Column(
            "category",
            sa.Enum(
                "misread",
                "content_gap",
                "careless",
                "calculation",
                "time_management",
                name="mistakecategory",
                native_enum=False,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("severity", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("confirmed_by_tutor", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "past_papers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("subject_id", sa.Integer(), sa.ForeignKey("subjects.id"), nullable=False),
        sa.Column("session_label", sa.String(length=64), nullable=False),
        sa.Column("paper_number", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "past_paper_attempts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("past_paper_id", sa.Integer(), sa.ForeignKey("past_papers.id"), nullable=False),
        sa.Column("student_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("raw_marks", sa.Integer(), nullable=False),
        sa.Column("max_marks", sa.Integer(), nullable=False),
        sa.Column("timed", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("attempted_at", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "grade_boundaries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("subject_id", sa.Integer(), sa.ForeignKey("subjects.id"), nullable=False),
        sa.Column("grade_label", sa.String(length=16), nullable=False),
        sa.Column("min_percentage", sa.Float(), nullable=False),
        sa.UniqueConstraint("organization_id", "subject_id", "grade_label"),
    )

    op.create_table(
        "readiness_weights",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey("organizations.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("tutor_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("weight_topic_mastery", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("weight_past_paper_performance", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("weight_homework_performance", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("weight_assessment_performance", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("weight_syllabus_coverage", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("weight_mistake_analysis", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("weight_consistency", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("half_life_days", sa.Float(), nullable=False, server_default="45.0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "factor_evaluations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("evaluation_run_id", sa.String(length=36), nullable=False),
        sa.Column("student_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("subject_id", sa.Integer(), sa.ForeignKey("subjects.id"), nullable=False),
        sa.Column("topic_id", sa.Integer(), sa.ForeignKey("topics.id"), nullable=True),
        sa.Column(
            "factor",
            sa.Enum(
                "topic_mastery",
                "past_paper_performance",
                "homework_performance",
                "assessment_performance",
                "syllabus_coverage",
                "mistake_analysis",
                "consistency",
                name="readinessfactor",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column(
            "confidence",
            sa.Enum(
                "no_data", "low", "medium", "high",
                name="factorconfidence", native_enum=False, length=8,
            ),
            nullable=False,
        ),
        sa.Column("evidence_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("detail", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_factor_evaluations_run_student_subject",
        "factor_evaluations",
        ["evaluation_run_id", "student_id", "subject_id"],
    )

    op.create_table(
        "readiness_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("evaluation_run_id", sa.String(length=36), nullable=False),
        sa.Column("student_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("subject_id", sa.Integer(), sa.ForeignKey("subjects.id"), nullable=False),
        sa.Column(
            "status",
            sa.Enum("ready", "failed", name="aisynthesisstatus", native_enum=False, length=8),
            nullable=False,
        ),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("predicted_grade", sa.String(length=16), nullable=True),
        sa.Column("weak_topics", sa.JSON(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("recommended_revision", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_readiness_snapshots_student_subject",
        "readiness_snapshots",
        ["student_id", "subject_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_readiness_snapshots_student_subject", table_name="readiness_snapshots")
    op.drop_table("readiness_snapshots")
    op.drop_index("ix_factor_evaluations_run_student_subject", table_name="factor_evaluations")
    op.drop_table("factor_evaluations")
    op.drop_table("readiness_weights")
    op.drop_table("grade_boundaries")
    op.drop_table("past_paper_attempts")
    op.drop_table("past_papers")
    op.drop_table("mistakes")
    with op.batch_alter_table("assignment_questions") as batch_op:
        batch_op.drop_column("unseen")
        batch_op.drop_column("difficulty")
