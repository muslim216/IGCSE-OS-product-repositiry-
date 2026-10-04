"""Zoom and Google Meet attendance integrations (task 7.3, AV-118).

Declared here as well as in migration 0064 (`DB-12`)."""

import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class MeetingProvider(str, enum.Enum):
    zoom = "zoom"
    google_meet = "google_meet"


class MeetingImportStatus(str, enum.Enum):
    queued = "queued"
    succeeded = "succeeded"
    failed = "failed"


class MeetingConnection(TimestampMixin, Base):
    """A tutor's connected Zoom or Google account — one per (tutor, provider).
    The refresh token is stored encrypted and is the only long-lived credential;
    access tokens are minted on demand and never persisted. Never logged."""

    __tablename__ = "meeting_connections"
    __table_args__ = (
        UniqueConstraint("tutor_id", "provider", name="uq_meeting_connections_tutor_id_provider"),
        Index("ix_meeting_connections_organization_id", "organization_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    tutor_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    provider: Mapped[MeetingProvider] = mapped_column(
        Enum(MeetingProvider, native_enum=False, length=12), nullable=False
    )
    encrypted_refresh_token: Mapped[str] = mapped_column(Text, nullable=False)
    # NULL when the provider did not say; shown as such, never invented.
    account_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    scopes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    connected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MeetingParticipant(TimestampMixin, Base):
    """Someone the provider says was in a lesson's meeting. How an unmatched
    participant reaches the tutor: a participant is matched to a student only by
    exact email, and everyone else is listed here for a human to decide
    (`PROD-1`) — never guessed from a name."""

    __tablename__ = "meeting_participants"
    __table_args__ = (
        Index("ix_meeting_participants_lesson_id", "lesson_id"),
        Index("ix_meeting_participants_organization_id", "organization_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    # CASCADE in Postgres; SQLite (tests) has FKs off, so the lesson delete
    # removes these rows explicitly as well.
    lesson_id: Mapped[int] = mapped_column(
        ForeignKey("lessons.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[MeetingProvider] = mapped_column(
        Enum(MeetingProvider, native_enum=False, length=12), nullable=False
    )
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    matched_student_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    # An email that matched a student but that the provider did not verify (a Zoom
    # guest types their own): shown to the tutor pre-selected, never acted on.
    suggested_student_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    # Set only when a tutor chose the student; a re-import never wipes such a row.
    resolved_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)


class LessonMeetingImport(TimestampMixin, Base):
    """The last attendance import for a lesson, so a failure is something the
    tutor sees rather than a register that quietly stays empty. One row per lesson."""

    __tablename__ = "lesson_meeting_imports"
    __table_args__ = (Index("ix_lesson_meeting_imports_organization_id", "organization_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    lesson_id: Mapped[int] = mapped_column(
        ForeignKey("lessons.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    status: Mapped[MeetingImportStatus] = mapped_column(
        Enum(MeetingImportStatus, native_enum=False, length=10), nullable=False
    )
    # Machine-readable reason on failure (not_connected, auth_failed, ...).
    error_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    # When the current import was asked for: a `queued` row older than this
    # window is treated as lost, not as still running.
    # Which request the current import is. A job carries the number it was queued
    # with; a worker whose number is no longer this one (the import was re-asked
    # after a presumed loss) must not write status or attendance.
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
