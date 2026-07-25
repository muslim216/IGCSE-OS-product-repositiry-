"""google_accounts + classroom_course_links + classroom_work_links (Google Classroom integration)

Revision ID: 0017
Revises: 0016
Create Date: 2026-07-24

"""
from alembic import op
import sqlalchemy as sa

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "google_accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("tutor_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, unique=True),
        sa.Column("google_email", sa.String(length=255), nullable=False),
        sa.Column("encrypted_refresh_token", sa.Text(), nullable=False),
        sa.Column("scopes", sa.Text(), nullable=False),
        sa.Column("connected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "classroom_course_links",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("google_account_id", sa.Integer(), sa.ForeignKey("google_accounts.id"), nullable=False),
        sa.Column("group_id", sa.Integer(), sa.ForeignKey("groups.id"), nullable=False, unique=True),
        sa.Column("classroom_course_id", sa.String(length=64), nullable=False),
        sa.Column("classroom_course_name", sa.String(length=255), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "google_account_id", "classroom_course_id", name="uq_course_link_account_course"
        ),
    )
    op.create_table(
        "classroom_work_links",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "course_link_id", sa.Integer(), sa.ForeignKey("classroom_course_links.id"), nullable=False
        ),
        sa.Column("assignment_id", sa.Integer(), sa.ForeignKey("assignments.id"), nullable=False, unique=True),
        sa.Column("classroom_coursework_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "course_link_id", "classroom_coursework_id", name="uq_work_link_course_coursework"
        ),
    )


def downgrade() -> None:
    op.drop_table("classroom_work_links")
    op.drop_table("classroom_course_links")
    op.drop_table("google_accounts")
