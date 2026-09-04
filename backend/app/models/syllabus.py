import enum

from sqlalchemy import (
    JSON,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class Subject(Base):
    __tablename__ = "subjects"
    __table_args__ = (UniqueConstraint("exam_board", "code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    exam_board: Mapped[str] = mapped_column(String(64), nullable=False)
    code: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    # "9-1" (Edexcel IGCSE) or "A*-E" (Cambridge O Level)
    grade_scale: Mapped[str] = mapped_column(String(16), nullable=False)
    # Ordered list of {"grade": "9", "min": 90} — readiness % → predicted grade.
    grade_boundaries: Mapped[list] = mapped_column(JSON, nullable=False)

    topics: Mapped[list["Topic"]] = relationship(
        back_populates="subject", cascade="all, delete-orphan"
    )
    chapters: Mapped[list["Chapter"]] = relationship(
        back_populates="subject", cascade="all, delete-orphan", order_by="Chapter.position"
    )


class Chapter(Base):
    """A unit of the syllabus between Subject and Topic (AV-9, E1).

    A chapter is what the teaching plan schedules and what a classified belongs
    to, and it carries its own rolled-up readiness — none of which a
    `Topic.parent_id` row can express, because it would also be a markable topic.
    So this is a distinct table, and `Topic.parent_id` stays for genuine
    sub-topics beneath a chapter's topics.

    Marks, mistakes and readiness attach at *topic* level; a chapter's score is
    rolled up from its topics and is never stored on the topic rows.
    """

    __tablename__ = "chapters"
    __table_args__ = (
        UniqueConstraint("subject_id", "code"),
        # Every read of a chapter is "the chapters of this subject, in order" —
        # the plan's schedule, the review UI, the rollup. Declared here as well
        # as in migration 0029, per DB-12.
        Index("ix_chapters_subject_id_position", "subject_id", "position"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"), nullable=False)
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    # Teaching order within the subject, tutor-controlled. Not derived from
    # `code` — a tutor may teach chapter 4 before chapter 3.
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    weight: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)

    subject: Mapped[Subject] = relationship(back_populates="chapters")
    topics: Mapped[list["Topic"]] = relationship(back_populates="chapter")


class Topic(Base):
    __tablename__ = "topics"
    __table_args__ = (
        UniqueConstraint("subject_id", "code"),
        # The rollup reads a chapter's topics; so does every chapter-scoped
        # surface from Phase 6 on. Declared here as well as in 0029 (DB-12).
        Index("ix_topics_chapter_id", "chapter_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"), nullable=False)
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    # Nullable until syllabus extraction is chapter-first (task 2.3): a topic
    # drafted by today's flat extractor has no chapter to point at, and
    # inventing one would fabricate structure the tutor never approved (PROD-2).
    chapter_id: Mapped[int | None] = mapped_column(ForeignKey("chapters.id"), nullable=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("topics.id"), nullable=True)
    weight: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)

    subject: Mapped[Subject] = relationship(back_populates="topics")
    chapter: Mapped["Chapter | None"] = relationship(back_populates="topics")


class SyllabusUploadStatus(str, enum.Enum):
    extracting = "extracting"
    extraction_failed = "extraction_failed"
    review = "review"
    applied = "applied"


class SyllabusUpload(TimestampMixin, Base):
    """A syllabus document a tutor uploads; the AI drafts a topic tree from it
    for the tutor to review/edit before it's applied as a real Subject."""

    __tablename__ = "syllabus_uploads"

    id: Mapped[int] = mapped_column(primary_key=True)
    tutor_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str] = mapped_column(String(255), nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_mime: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[SyllabusUploadStatus] = mapped_column(
        Enum(SyllabusUploadStatus, native_enum=False, length=20),
        default=SyllabusUploadStatus.extracting,
        nullable=False,
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # AI-drafted (and tutor-editable) syllabus data: exam_board, code, name,
    # grade_scale, grade_boundaries, topics — same shape as seed/syllabus/*.json.
    draft: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    subject_id: Mapped[int | None] = mapped_column(ForeignKey("subjects.id"), nullable=True)
