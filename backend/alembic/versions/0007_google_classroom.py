"""google classroom integration

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-28

"""
from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

IMPORT_OUTCOMES = (
    "imported",
    "skipped_unmapped",
    "skipped_not_turned_in",
    "skipped_no_attachments",
    "skipped_finalized",
    "unsupported_files",
    "failed",
)


def upgrade() -> None:
    op.create_table(
        "google_accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tutor_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("google_sub", sa.String(length=64), nullable=False),
        sa.Column("google_email", sa.String(length=255), nullable=True),
        sa.Column("access_token", sa.Text(), nullable=True),
        sa.Column("refresh_token", sa.Text(), nullable=True),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scopes", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.Enum("connected", "needs_reauth", name="googleaccountstatus", native_enum=False, length=16),
            nullable=False,
        ),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tutor_id"),
    )

    op.create_table(
        "google_course_links",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("google_accounts.id"), nullable=False),
        sa.Column("group_id", sa.Integer(), sa.ForeignKey("groups.id"), nullable=False),
        sa.Column("course_id", sa.String(length=32), nullable=False),
        sa.Column("course_name", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("group_id"),
        sa.UniqueConstraint("account_id", "course_id"),
    )

    op.create_table(
        "google_student_links",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("google_accounts.id"), nullable=False),
        sa.Column("student_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("google_user_id", sa.String(length=32), nullable=False),
        sa.Column("google_email", sa.String(length=255), nullable=True),
        sa.Column("google_name", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("account_id", "google_user_id"),
    )

    op.create_table(
        "google_coursework_links",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "course_link_id", sa.Integer(), sa.ForeignKey("google_course_links.id"), nullable=False
        ),
        sa.Column("assignment_id", sa.Integer(), sa.ForeignKey("assignments.id"), nullable=False),
        sa.Column("coursework_id", sa.String(length=32), nullable=False),
        sa.Column("coursework_title", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("assignment_id"),
        sa.UniqueConstraint("course_link_id", "coursework_id"),
    )

    op.create_table(
        "google_submission_imports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "coursework_link_id",
            sa.Integer(),
            sa.ForeignKey("google_coursework_links.id"),
            nullable=False,
        ),
        sa.Column("gc_submission_id", sa.String(length=64), nullable=False),
        sa.Column("google_user_id", sa.String(length=32), nullable=False),
        sa.Column("submission_id", sa.Integer(), sa.ForeignKey("submissions.id"), nullable=True),
        sa.Column(
            "outcome",
            sa.Enum(*IMPORT_OUTCOMES, name="importoutcome", native_enum=False, length=24),
            nullable=False,
        ),
        sa.Column("gc_update_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("imported_file_count", sa.Integer(), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("coursework_link_id", "gc_submission_id"),
    )

    op.create_table(
        "google_import_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "coursework_link_id",
            sa.Integer(),
            sa.ForeignKey("google_coursework_links.id"),
            nullable=False,
        ),
        sa.Column("started_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "status",
            sa.Enum("pending", "running", "done", "failed", name="importrunstatus", native_enum=False, length=12),
            nullable=False,
        ),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("imported", sa.Integer(), nullable=False),
        sa.Column("skipped", sa.Integer(), nullable=False),
        sa.Column("failed", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("google_import_runs")
    op.drop_table("google_submission_imports")
    op.drop_table("google_coursework_links")
    op.drop_table("google_student_links")
    op.drop_table("google_course_links")
    op.drop_table("google_accounts")
