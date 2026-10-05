"""Notifications: contact points, preferences, the outbox, org send settings

Task 8.1. WhatsApp is the main channel and email the fallback. `contact_points`
holds where each person can be reached (confirmed by the tutor before anything
is sent), `notification_preferences` per-channel opt-outs (absence = enabled),
`notifications` the outbox a job drains. Organizations gain the weekly send
moment (AV-88/89) and the AI/template language (AV-66).

Existing table altered, so `batch_alter_table` with the naming convention
(`DB-17`). Enums are non-native strings (`DB-5`).

Revision ID: 0065
Revises: 0064
Create Date: 2026-10-05

"""

import sqlalchemy as sa

from alembic import op

NAMING = {
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
}

revision = "0065"
down_revision = "0064"
branch_labels = None
depends_on = None


def _channel() -> sa.Enum:
    return sa.Enum("whatsapp", "email", name="notificationchannel", native_enum=False, length=16)


def _kind() -> sa.Enum:
    return sa.Enum(
        "weekly_send",
        "homework_set",
        "homework_due",
        "marked_work_ready",
        "lesson_reminder",
        "review_queue",
        "invite",
        "contact_confirm",
        name="notificationkind",
        native_enum=False,
        length=24,
    )


def upgrade() -> None:
    with op.batch_alter_table("organizations", naming_convention=NAMING) as batch:
        batch.add_column(
            sa.Column("weekly_send_weekday", sa.Integer(), nullable=False, server_default="6")
        )
        batch.add_column(
            sa.Column("weekly_send_hour", sa.Integer(), nullable=False, server_default="17")
        )
        batch.add_column(
            sa.Column("ai_language", sa.String(length=8), nullable=False, server_default="en")
        )

    op.create_table(
        "contact_points",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey(
                "organizations.id", name="fk_contact_points_organization_id_organizations"
            ),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", name="fk_contact_points_user_id_users"),
            nullable=False,
        ),
        sa.Column("channel", _channel(), nullable=False),
        sa.Column("address", sa.String(length=255), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "confirmed_by_id",
            sa.Integer(),
            sa.ForeignKey("users.id", name="fk_contact_points_confirmed_by_id_users"),
            nullable=True,
        ),
        sa.Column("suppressed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "suppressed_reason",
            sa.Enum(
                "opted_out",
                "bounced",
                "complaint",
                "provider_rejected",
                name="suppressionreason",
                native_enum=False,
                length=24,
            ),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "channel", name="uq_contact_points_user_channel"),
    )

    op.create_table(
        "whatsapp_opt_outs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("address", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("address", name="uq_whatsapp_opt_outs_address"),
    )

    op.create_table(
        "notification_preferences",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", name="fk_notification_preferences_user_id_users"),
            nullable=False,
        ),
        sa.Column("kind", _kind(), nullable=False),
        sa.Column("channel", _channel(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "user_id", "kind", "channel", name="uq_notification_preferences_user_kind_channel"
        ),
    )

    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey(
                "organizations.id", name="fk_notifications_organization_id_organizations"
            ),
            nullable=False,
        ),
        sa.Column(
            "recipient_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", name="fk_notifications_recipient_user_id_users"),
            nullable=False,
        ),
        sa.Column("kind", _kind(), nullable=False),
        sa.Column("channel", _channel(), nullable=True),
        sa.Column("template", sa.String(length=64), nullable=False),
        sa.Column("params", sa.JSON(), nullable=False),
        sa.Column("link_path", sa.String(length=255), nullable=False),
        sa.Column("idempotency_key", sa.String(length=190), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "queued",
                "sent",
                "failed",
                "suppressed",
                "no_channel",
                "channel_unconfigured",
                name="notificationstatus",
                native_enum=False,
                length=24,
            ),
            nullable=False,
        ),
        sa.Column("provider_message_id", sa.String(length=255), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("idempotency_key", name="uq_notifications_idempotency_key"),
    )
    op.create_index(
        "ix_notifications_recipient_created",
        "notifications",
        ["recipient_user_id", "created_at"],
    )
    op.create_index(
        "ix_notifications_provider_message_id", "notifications", ["provider_message_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_notifications_provider_message_id", table_name="notifications")
    op.drop_index("ix_notifications_recipient_created", table_name="notifications")
    op.drop_table("notifications")
    op.drop_table("notification_preferences")
    op.drop_table("whatsapp_opt_outs")
    op.drop_table("contact_points")
    with op.batch_alter_table("organizations", naming_convention=NAMING) as batch:
        batch.drop_column("ai_language")
        batch.drop_column("weekly_send_hour")
        batch.drop_column("weekly_send_weekday")
