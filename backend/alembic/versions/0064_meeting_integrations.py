"""Zoom and Google Meet attendance integrations

Task 7.3 (AV-118). `meeting_connections` holds a tutor's connected account per
provider (refresh token encrypted, never an access token). `lessons` gains the
meeting an online lesson was held in. `meeting_participants` is where everyone
the provider reported lands, so an unmatched one can be shown to the tutor
instead of guessed at. `lesson_meeting_imports` is the last import's outcome, so
a failed one is visible rather than silent.

Existing table altered, so `batch_alter_table` with the naming convention
(`DB-17`). Enums are non-native strings (`DB-5`).

Revision ID: 0064
Revises: 0063
Create Date: 2026-10-04

"""

import sqlalchemy as sa

from alembic import op

NAMING = {
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
}

revision = "0064"
down_revision = "0063"
branch_labels = None
depends_on = None


def _provider() -> sa.Enum:
    return sa.Enum("zoom", "google_meet", name="meetingprovider", native_enum=False, length=12)


def upgrade() -> None:
    with op.batch_alter_table("lessons", naming_convention=NAMING) as batch:
        batch.add_column(sa.Column("meeting_provider", _provider(), nullable=True))
        batch.add_column(sa.Column("meeting_ref", sa.String(length=64), nullable=True))

    op.create_table(
        "meeting_connections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey(
                "organizations.id", name="fk_meeting_connections_organization_id_organizations"
            ),
            nullable=False,
        ),
        sa.Column(
            "tutor_id",
            sa.Integer(),
            sa.ForeignKey("users.id", name="fk_meeting_connections_tutor_id_users"),
            nullable=False,
        ),
        sa.Column("provider", _provider(), nullable=False),
        sa.Column("encrypted_refresh_token", sa.Text(), nullable=False),
        sa.Column("account_email", sa.String(length=255), nullable=True),
        sa.Column("scopes", sa.Text(), nullable=False),
        sa.Column("connected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "tutor_id", "provider", name="uq_meeting_connections_tutor_id_provider"
        ),
    )
    op.create_index(
        "ix_meeting_connections_organization_id", "meeting_connections", ["organization_id"]
    )

    op.create_table(
        "meeting_participants",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey(
                "organizations.id", name="fk_meeting_participants_organization_id_organizations"
            ),
            nullable=False,
        ),
        sa.Column(
            "lesson_id",
            sa.Integer(),
            sa.ForeignKey(
                "lessons.id", ondelete="CASCADE", name="fk_meeting_participants_lesson_id_lessons"
            ),
            nullable=False,
        ),
        sa.Column("provider", _provider(), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=False),
        sa.Column(
            "matched_student_id",
            sa.Integer(),
            sa.ForeignKey("users.id", name="fk_meeting_participants_matched_student_id_users"),
            nullable=True,
        ),
        sa.Column(
            "suggested_student_id",
            sa.Integer(),
            sa.ForeignKey("users.id", name="fk_meeting_participants_suggested_student_id_users"),
            nullable=True,
        ),
        sa.Column(
            "resolved_by_id",
            sa.Integer(),
            sa.ForeignKey("users.id", name="fk_meeting_participants_resolved_by_id_users"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_meeting_participants_lesson_id", "meeting_participants", ["lesson_id"])
    op.create_index(
        "ix_meeting_participants_organization_id", "meeting_participants", ["organization_id"]
    )

    op.create_table(
        "lesson_meeting_imports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey(
                "organizations.id", name="fk_lesson_meeting_imports_organization_id_organizations"
            ),
            nullable=False,
        ),
        sa.Column(
            "lesson_id",
            sa.Integer(),
            sa.ForeignKey(
                "lessons.id",
                ondelete="CASCADE",
                name="fk_lesson_meeting_imports_lesson_id_lessons",
            ),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "queued",
                "succeeded",
                "failed",
                name="meetingimportstatus",
                native_enum=False,
                length=10,
            ),
            nullable=False,
        ),
        sa.Column("error_code", sa.String(length=32), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column(
            "requested_by_id",
            sa.Integer(),
            sa.ForeignKey("users.id", name="fk_lesson_meeting_imports_requested_by_id_users"),
            nullable=False,
        ),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_lesson_meeting_imports_organization_id",
        "lesson_meeting_imports",
        ["organization_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_lesson_meeting_imports_organization_id", table_name="lesson_meeting_imports")
    op.drop_table("lesson_meeting_imports")

    op.drop_index("ix_meeting_participants_organization_id", table_name="meeting_participants")
    op.drop_index("ix_meeting_participants_lesson_id", table_name="meeting_participants")
    op.drop_table("meeting_participants")

    op.drop_index("ix_meeting_connections_organization_id", table_name="meeting_connections")
    op.drop_table("meeting_connections")

    with op.batch_alter_table("lessons", naming_convention=NAMING) as batch:
        batch.drop_column("meeting_ref")
        batch.drop_column("meeting_provider")
