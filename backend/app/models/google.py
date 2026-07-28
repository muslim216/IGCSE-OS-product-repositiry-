"""Google Classroom integration.

The tutor connects one Google account; links a Classroom course to a class and
its students to app accounts once; then each import pulls a coursework item's
submissions into the existing Submission + AI marking pipeline.
"""

import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class GoogleAccountStatus(str, enum.Enum):
    connected = "connected"
    needs_reauth = "needs_reauth"


class GoogleAccount(TimestampMixin, Base):
    """A tutor's connected Google account. One per tutor."""

    __tablename__ = "google_accounts"
    __table_args__ = (UniqueConstraint("tutor_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tutor_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    google_sub: Mapped[str] = mapped_column(String(64), nullable=False)
    google_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    access_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Encrypted at rest — a plaintext dump would hand over the teacher's Drive.
    refresh_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scopes: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[GoogleAccountStatus] = mapped_column(
        Enum(GoogleAccountStatus, native_enum=False, length=16),
        default=GoogleAccountStatus.connected,
        nullable=False,
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class GoogleCourseLink(TimestampMixin, Base):
    """A Classroom course paired with an app class."""

    __tablename__ = "google_course_links"
    __table_args__ = (
        UniqueConstraint("group_id"),
        UniqueConstraint("account_id", "course_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("google_accounts.id"), nullable=False)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"), nullable=False)
    course_id: Mapped[str] = mapped_column(String(32), nullable=False)
    course_name: Mapped[str | None] = mapped_column(String(255), nullable=True)


class GoogleStudentLink(TimestampMixin, Base):
    """A Classroom student mapped to an app account.

    Keyed on the Classroom profile id, which is stable and always present —
    emails are often missing on these accounts and names change. Scoped to the
    account rather than the course, so mapping a student once carries across
    every class that tutor runs.
    """

    __tablename__ = "google_student_links"
    __table_args__ = (UniqueConstraint("account_id", "google_user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("google_accounts.id"), nullable=False)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    google_user_id: Mapped[str] = mapped_column(String(32), nullable=False)
    google_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    google_name: Mapped[str | None] = mapped_column(String(255), nullable=True)


class GoogleCourseworkLink(TimestampMixin, Base):
    """A Classroom coursework item paired with an app assignment."""

    __tablename__ = "google_coursework_links"
    __table_args__ = (
        UniqueConstraint("assignment_id"),
        UniqueConstraint("course_link_id", "coursework_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    course_link_id: Mapped[int] = mapped_column(
        ForeignKey("google_course_links.id"), nullable=False
    )
    assignment_id: Mapped[int] = mapped_column(ForeignKey("assignments.id"), nullable=False)
    coursework_id: Mapped[str] = mapped_column(String(32), nullable=False)
    coursework_title: Mapped[str | None] = mapped_column(String(255), nullable=True)


class ImportOutcome(str, enum.Enum):
    imported = "imported"
    skipped_unmapped = "skipped_unmapped"
    skipped_not_turned_in = "skipped_not_turned_in"
    skipped_no_attachments = "skipped_no_attachments"
    skipped_finalized = "skipped_finalized"
    unsupported_files = "unsupported_files"
    failed = "failed"


class GoogleSubmissionImport(TimestampMixin, Base):
    """One Classroom submission's import result.

    The unique constraint is the idempotency mechanism: re-running an import
    can't duplicate work even if two runs race.
    """

    __tablename__ = "google_submission_imports"
    __table_args__ = (UniqueConstraint("coursework_link_id", "gc_submission_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    coursework_link_id: Mapped[int] = mapped_column(
        ForeignKey("google_coursework_links.id"), nullable=False
    )
    gc_submission_id: Mapped[str] = mapped_column(String(64), nullable=False)
    google_user_id: Mapped[str] = mapped_column(String(32), nullable=False)
    submission_id: Mapped[int | None] = mapped_column(ForeignKey("submissions.id"), nullable=True)
    outcome: Mapped[ImportOutcome] = mapped_column(
        Enum(ImportOutcome, native_enum=False, length=24), nullable=False
    )
    # Classroom's updateTime as of the last import, so a genuine resubmission
    # can be told apart from a repeat run.
    gc_update_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    imported_file_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)


class ImportRunStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    done = "done"
    failed = "failed"


class GoogleImportRun(TimestampMixin, Base):
    """Progress for one import, since downloading attachments takes minutes."""

    __tablename__ = "google_import_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    coursework_link_id: Mapped[int] = mapped_column(
        ForeignKey("google_coursework_links.id"), nullable=False
    )
    started_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    status: Mapped[ImportRunStatus] = mapped_column(
        Enum(ImportRunStatus, native_enum=False, length=12),
        default=ImportRunStatus.pending,
        nullable=False,
    )
    total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    imported: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    skipped: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
