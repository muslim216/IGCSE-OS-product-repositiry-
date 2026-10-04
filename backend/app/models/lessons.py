import enum
from datetime import date, datetime, time

from sqlalchemy import (
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Text,
    Time,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class LessonMode(str, enum.Enum):
    in_person = "in_person"
    online = "online"


class LessonOrigin(str, enum.Enum):
    """Who said this lesson happened. `plan` is a lesson auto-recorded from the
    plan because nobody said otherwise (AV-119) — kept apart so it stays
    traceable (`PROD-1`)."""

    tutor = "tutor"
    plan = "plan"


class AttendanceState(str, enum.Enum):
    # Two states only (owner decision 2026-10-04): no late, no excused. A
    # student with no row was simply not recorded — never read that as absent.
    present = "present"
    absent = "absent"


class AttendanceSource(str, enum.Enum):
    tutor = "tutor"
    zoom = "zoom"
    google_meet = "google_meet"


class Lesson(TimestampMixin, Base):
    """A taught lesson: date, notes, topics covered, and per-student
    observations. The core entity the Avora operating loop revolves around —
    teach -> assign -> submit -> AI analyze -> update CRM & readiness ->
    review -> plan the next lesson."""

    __tablename__ = "lessons"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    duration_min: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The recurring template this lesson was created from, if any — ad hoc
    # lessons (no template) leave this null.
    schedule_slot_id: Mapped[int | None] = mapped_column(
        ForeignKey("schedule_slots.id"), nullable=True
    )
    # Existing lessons backfill to in_person in migration 0063.
    mode: Mapped[LessonMode] = mapped_column(
        Enum(LessonMode, native_enum=False, length=10),
        default=LessonMode.in_person,
        server_default=LessonMode.in_person.value,
        nullable=False,
    )
    # Local wall-clock time in the organization's timezone. NULL means unknown:
    # never read it as midnight (`DB-9`).
    start_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    origin: Mapped[LessonOrigin] = mapped_column(
        Enum(LessonOrigin, native_enum=False, length=10),
        default=LessonOrigin.tutor,
        server_default=LessonOrigin.tutor.value,
        nullable=False,
    )


class LessonTopic(Base):
    """A syllabus topic covered in a lesson — becomes "taught" for every
    student in the group as of the lesson date. The evidence-based root of
    the Syllabus Coverage readiness factor."""

    __tablename__ = "lesson_topics"
    __table_args__ = (UniqueConstraint("lesson_id", "topic_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    lesson_id: Mapped[int] = mapped_column(ForeignKey("lessons.id"), nullable=False)
    topic_id: Mapped[int] = mapped_column(ForeignKey("topics.id"), nullable=False)


class LessonObservation(TimestampMixin, Base):
    """A tutor's per-student note tied to a specific lesson, optionally rated
    on a topic — feeds Evidence exactly like a free-floating TutorObservation."""

    __tablename__ = "lesson_observations"

    id: Mapped[int] = mapped_column(primary_key=True)
    lesson_id: Mapped[int] = mapped_column(ForeignKey("lessons.id"), nullable=False)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    topic_id: Mapped[int | None] = mapped_column(ForeignKey("topics.id"), nullable=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 0..100


class LessonAttendance(TimestampMixin, Base):
    """Whether a student was present at a lesson. One row per (lesson, student).

    No row means attendance was not taken for that student — never absent
    (`PROD-2`). Attendance is not a readiness factor (AV-33): nothing here is
    `Evidence`. Declared here as well as in migration 0063 (`DB-12`)."""

    __tablename__ = "lesson_attendance"
    __table_args__ = (
        UniqueConstraint(
            "lesson_id", "student_id", name="uq_lesson_attendance_lesson_id_student_id"
        ),
        Index("ix_lesson_attendance_student_id", "student_id"),
        Index("ix_lesson_attendance_organization_id", "organization_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    # CASCADE in Postgres; SQLite (tests) has FKs off, so `delete_lesson`
    # removes these rows explicitly as well.
    lesson_id: Mapped[int] = mapped_column(
        ForeignKey("lessons.id", ondelete="CASCADE"), nullable=False
    )
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    state: Mapped[AttendanceState] = mapped_column(
        Enum(AttendanceState, native_enum=False, length=10), nullable=False
    )
    source: Mapped[AttendanceSource] = mapped_column(
        Enum(AttendanceSource, native_enum=False, length=12), nullable=False
    )
    # NULL for integration writes (Zoom / Meet): nobody at Avora recorded them.
    recorded_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
