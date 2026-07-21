"""syllabus_uploads (AI-parsed syllabus PDF upload)

Revision ID: 0011
Revises: 0010
Create Date: 2026-07-21

"""
from alembic import op
import sqlalchemy as sa

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "syllabus_uploads",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tutor_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("file_path", sa.String(length=255), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("file_mime", sa.String(length=128), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "extracting",
                "extraction_failed",
                "review",
                "applied",
                name="syllabusuploadstatus",
                native_enum=False,
                length=20,
            ),
            nullable=False,
            server_default="extracting",
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("draft", sa.JSON(), nullable=True),
        sa.Column("subject_id", sa.Integer(), sa.ForeignKey("subjects.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("syllabus_uploads")
