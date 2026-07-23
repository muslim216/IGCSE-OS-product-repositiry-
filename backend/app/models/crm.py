from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, utcnow


class StudentProfile(TimestampMixin, Base):
    """The student's CRM record — everything about them beyond their login.
    One row per student, created lazily the first time a tutor edits it."""

    __tablename__ = "student_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, unique=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    school: Mapped[str | None] = mapped_column(String(255), nullable=True)
    year_group: Mapped[str | None] = mapped_column(String(64), nullable=True)
    parent_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    parent_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    parent_phone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class StudentSubject(TimestampMixin, Base):
    """A subject enrollment: this student is doing this subject, with this
    target grade — independent of which tutoring Group(s) cover it."""

    __tablename__ = "student_subjects"
    __table_args__ = (UniqueConstraint("student_id", "subject_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"), nullable=False)
    target_grade: Mapped[str | None] = mapped_column(String(16), nullable=True)


class TutorNote(TimestampMixin, Base):
    """An append-only timeline entry a tutor writes about a student —
    context, observations, reminders. Distinct from per-lesson observations."""

    __tablename__ = "tutor_notes"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    tutor_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)


class ParentCommunication(TimestampMixin, Base):
    """A log entry of a conversation or message with a student's parent."""

    __tablename__ = "parent_communications"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    tutor_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
