"""classifieds, assignments, submissions, marks, jobs

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-19

"""

import sqlalchemy as sa

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "classifieds",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tutor_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("subject_id", sa.Integer(), sa.ForeignKey("subjects.id"), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("file_path", sa.String(length=255), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("file_mime", sa.String(length=128), nullable=False),
        sa.Column("mark_scheme_path", sa.String(length=255), nullable=True),
        sa.Column("mark_scheme_name", sa.String(length=255), nullable=True),
        sa.Column("mark_scheme_mime", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "assignments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("group_id", sa.Integer(), sa.ForeignKey("groups.id"), nullable=False),
        sa.Column("classified_id", sa.Integer(), sa.ForeignKey("classifieds.id"), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("instructions", sa.Text(), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("question_range", sa.String(length=128), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "extracting",
                "extraction_failed",
                "review",
                "published",
                "closed",
                name="assignmentstatus",
                native_enum=False,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("extraction_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "assignment_questions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("assignment_id", sa.Integer(), sa.ForeignKey("assignments.id"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("number", sa.String(length=16), nullable=False),
        sa.Column("text_summary", sa.Text(), nullable=False),
        sa.Column("max_marks", sa.Integer(), nullable=False),
        sa.Column("has_mark_scheme", sa.Boolean(), nullable=False),
    )
    op.create_table(
        "question_topics",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "question_id", sa.Integer(), sa.ForeignKey("assignment_questions.id"), nullable=False
        ),
        sa.Column("topic_id", sa.Integer(), sa.ForeignKey("topics.id"), nullable=False),
        sa.UniqueConstraint("question_id", "topic_id"),
    )
    op.create_table(
        "submissions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("assignment_id", sa.Integer(), sa.ForeignKey("assignments.id"), nullable=False),
        sa.Column("student_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "submitted",
                "marking",
                "ai_marked",
                "ai_failed",
                "finalized",
                name="submissionstatus",
                native_enum=False,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("ai_error", sa.Text(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finalized_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("assignment_id", "student_id"),
    )
    op.create_table(
        "submission_files",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("submission_id", sa.Integer(), sa.ForeignKey("submissions.id"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("path", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("mime", sa.String(length=128), nullable=False),
    )
    op.create_table(
        "question_marks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("submission_id", sa.Integer(), sa.ForeignKey("submissions.id"), nullable=False),
        sa.Column(
            "question_id", sa.Integer(), sa.ForeignKey("assignment_questions.id"), nullable=False
        ),
        sa.Column("ai_transcription", sa.Text(), nullable=True),
        sa.Column("ai_marks", sa.Integer(), nullable=True),
        sa.Column("ai_feedback", sa.Text(), nullable=True),
        sa.Column(
            "ai_confidence",
            sa.Enum(
                "high",
                "medium",
                "low",
                "tutor_only",
                name="markconfidence",
                native_enum=False,
                length=16,
            ),
            nullable=True,
        ),
        sa.Column("final_marks", sa.Integer(), nullable=True),
        sa.Column("final_feedback", sa.Text(), nullable=True),
        sa.Column("overridden", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("submission_id", "question_id"),
    )
    op.create_table(
        "jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "running",
                "done",
                "failed",
                name="jobstatus",
                native_enum=False,
                length=12,
            ),
            nullable=False,
        ),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    for table in (
        "jobs",
        "question_marks",
        "submission_files",
        "submissions",
        "question_topics",
        "assignment_questions",
        "assignments",
        "classifieds",
    ):
        op.drop_table(table)
