from datetime import date

from sqlalchemy import Date, ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


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
