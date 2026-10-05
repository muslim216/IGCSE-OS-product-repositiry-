"""The stored weekly send (task 8.2): one row per reader per week."""

import enum
from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class WeeklySendAudience(str, enum.Enum):
    tutor = "tutor"
    student = "student"
    parent = "parent"


class WeeklySend(TimestampMixin, Base):
    """What one person was told about one week — the artifact their home page
    links to and the WhatsApp message points at (AV-51).

    Stored, not recomputed on read: the facts are "as at the send moment", and a
    report a parent opens on Thursday must say what it said on Sunday. `facts`
    holds numbers, names and states only, never a student's free text (threat
    review F9); `paragraphs` are copies of the stored narrative rows that
    existed at the send, so the screen and the send cannot disagree about the
    same child (AV-99).
    """

    __tablename__ = "weekly_sends"
    __table_args__ = (
        # One send per reader per week: what makes building a week twice a no-op.
        UniqueConstraint("recipient_user_id", "week_end", name="uq_weekly_sends_recipient_week"),
        Index("ix_weekly_sends_org_week", "organization_id", "week_end"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    recipient_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    audience: Mapped[WeeklySendAudience] = mapped_column(
        Enum(WeeklySendAudience, native_enum=False, length=16), nullable=False
    )
    week_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    week_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    facts: Mapped[dict] = mapped_column(JSON, nullable=False)
    paragraphs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
