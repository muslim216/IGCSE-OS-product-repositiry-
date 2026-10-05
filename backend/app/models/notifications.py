"""Contact points, notification preferences and the notification outbox (8.1).

WhatsApp is the main channel and email the fallback. A `Notification` row is
written first and sent by a job afterwards, so a send is never lost to a crash
and never doubled (`BE-6`): the unique `idempotency_key` is what makes a
re-enqueue a no-op.
"""

import enum
from datetime import datetime

from sqlalchemy import (
    JSON,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class NotificationChannel(str, enum.Enum):
    whatsapp = "whatsapp"
    email = "email"


class SuppressionReason(str, enum.Enum):
    opted_out = "opted_out"
    bounced = "bounced"
    complaint = "complaint"
    provider_rejected = "provider_rejected"


class NotificationKind(str, enum.Enum):
    weekly_send = "weekly_send"
    homework_set = "homework_set"
    homework_due = "homework_due"
    marked_work_ready = "marked_work_ready"
    lesson_reminder = "lesson_reminder"
    review_queue = "review_queue"
    invite = "invite"
    contact_confirm = "contact_confirm"


class NotificationStatus(str, enum.Enum):
    queued = "queued"
    sent = "sent"
    failed = "failed"
    suppressed = "suppressed"
    no_channel = "no_channel"
    channel_unconfigured = "channel_unconfigured"


class ContactPoint(TimestampMixin, Base):
    """Where one person can be reached on one channel.

    A tutor confirms an address after seeing it shown back (threat review F5):
    a mistyped or malicious number must not receive a child's results. Changing
    the address therefore clears the confirmation and any suppression.
    """

    __tablename__ = "contact_points"
    __table_args__ = (
        UniqueConstraint("user_id", "channel", name="uq_contact_points_user_channel"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    channel: Mapped[NotificationChannel] = mapped_column(
        Enum(NotificationChannel, native_enum=False, length=16), nullable=False
    )
    # E.164 for whatsapp, lowercased for email.
    address: Mapped[str] = mapped_column(String(255), nullable=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    suppressed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    suppressed_reason: Mapped[SuppressionReason | None] = mapped_column(
        Enum(SuppressionReason, native_enum=False, length=24), nullable=True
    )


class NotificationPreference(TimestampMixin, Base):
    """A per-channel opt-out. Absence of a row means enabled."""

    __tablename__ = "notification_preferences"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "kind", "channel", name="uq_notification_preferences_user_kind_channel"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    kind: Mapped[NotificationKind] = mapped_column(
        Enum(NotificationKind, native_enum=False, length=24), nullable=False
    )
    channel: Mapped[NotificationChannel] = mapped_column(
        Enum(NotificationChannel, native_enum=False, length=16), nullable=False
    )
    enabled: Mapped[bool] = mapped_column(nullable=False, default=True)


class Notification(TimestampMixin, Base):
    """The outbox. `params` holds numbers, enumerable values and short names
    only — never a student's free text (threat review F9)."""

    __tablename__ = "notifications"
    __table_args__ = (
        Index("ix_notifications_recipient_created", "recipient_user_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    recipient_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    kind: Mapped[NotificationKind] = mapped_column(
        Enum(NotificationKind, native_enum=False, length=24), nullable=False
    )
    channel: Mapped[NotificationChannel | None] = mapped_column(
        Enum(NotificationChannel, native_enum=False, length=16), nullable=True
    )
    template: Mapped[str] = mapped_column(String(64), nullable=False)
    params: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    link_path: Mapped[str] = mapped_column(String(255), nullable=False, default="/")
    idempotency_key: Mapped[str] = mapped_column(String(190), nullable=False, unique=True)
    status: Mapped[NotificationStatus] = mapped_column(
        Enum(NotificationStatus, native_enum=False, length=24),
        nullable=False,
        default=NotificationStatus.queued,
    )
    provider_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
