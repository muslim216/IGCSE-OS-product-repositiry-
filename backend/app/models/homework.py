import enum
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, utcnow


class Classified(TimestampMixin, Base):
    """A topic-compiled past-paper question booklet a tutor uploads and reuses."""

    __tablename__ = "classifieds"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    tutor_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str] = mapped_column(String(255), nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_mime: Mapped[str] = mapped_column(String(128), nullable=False)
    # Optional separate mark-scheme file; some classifieds include answers inline.
    mark_scheme_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mark_scheme_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mark_scheme_mime: Mapped[str | None] = mapped_column(String(128), nullable=True)


class AssignmentStatus(str, enum.Enum):
    extracting = "extracting"
    extraction_failed = "extraction_failed"
    review = "review"
    published = "published"
    closed = "closed"


class Assignment(TimestampMixin, Base):
    __tablename__ = "assignments"

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"), nullable=False)
    # The lesson this homework was assigned from, if any — direct
    # (lesson-less) assignments remain possible.
    lesson_id: Mapped[int | None] = mapped_column(ForeignKey("lessons.id"), nullable=True)
    # Optional: assignments can be created without a question booklet — the
    # tutor types questions directly instead of uploading/extracting a PDF.
    classified_id: Mapped[int | None] = mapped_column(ForeignKey("classifieds.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Free-text range like "Q1-15" or "pages 3-10"; passed to the AI extractor.
    question_range: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[AssignmentStatus] = mapped_column(
        Enum(AssignmentStatus, native_enum=False, length=20),
        default=AssignmentStatus.extracting,
        nullable=False,
    )
    extraction_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    classified: Mapped[Classified | None] = relationship()
    questions: Mapped[list["AssignmentQuestion"]] = relationship(
        back_populates="assignment", cascade="all, delete-orphan", order_by="AssignmentQuestion.position"
    )


class QuestionDifficulty(str, enum.Enum):
    easy = "easy"
    medium = "medium"
    hard = "hard"


class AssignmentQuestion(Base):
    __tablename__ = "assignment_questions"

    id: Mapped[int] = mapped_column(primary_key=True)
    assignment_id: Mapped[int] = mapped_column(ForeignKey("assignments.id"), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    number: Mapped[str] = mapped_column(String(16), nullable=False)
    text_summary: Mapped[str] = mapped_column(Text, nullable=False)
    max_marks: Mapped[int] = mapped_column(Integer, nullable=False)
    has_mark_scheme: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # AI-assigned at extraction, tutor-overridable in the review UI — feeds
    # the Topic Mastery readiness factor's difficulty-tiered breakdown.
    difficulty: Mapped[QuestionDifficulty | None] = mapped_column(
        Enum(QuestionDifficulty, native_enum=False, length=8), nullable=True
    )
    unseen: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    assignment: Mapped[Assignment] = relationship(back_populates="questions")
    topics: Mapped[list["QuestionTopic"]] = relationship(
        back_populates="question", cascade="all, delete-orphan"
    )


class QuestionTopic(Base):
    __tablename__ = "question_topics"
    __table_args__ = (UniqueConstraint("question_id", "topic_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("assignment_questions.id"), nullable=False)
    topic_id: Mapped[int] = mapped_column(ForeignKey("topics.id"), nullable=False)

    question: Mapped[AssignmentQuestion] = relationship(back_populates="topics")


class SubmissionStatus(str, enum.Enum):
    submitted = "submitted"
    marking = "marking"
    ai_marked = "ai_marked"
    ai_failed = "ai_failed"
    finalized = "finalized"


class Submission(TimestampMixin, Base):
    __tablename__ = "submissions"
    __table_args__ = (UniqueConstraint("assignment_id", "student_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    assignment_id: Mapped[int] = mapped_column(ForeignKey("assignments.id"), nullable=False)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    status: Mapped[SubmissionStatus] = mapped_column(
        Enum(SubmissionStatus, native_enum=False, length=16),
        default=SubmissionStatus.submitted,
        nullable=False,
    )
    ai_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finalized_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    assignment: Mapped[Assignment] = relationship()
    files: Mapped[list["SubmissionFile"]] = relationship(
        back_populates="submission", cascade="all, delete-orphan", order_by="SubmissionFile.position"
    )
    marks: Mapped[list["QuestionMark"]] = relationship(
        back_populates="submission", cascade="all, delete-orphan"
    )


class SubmissionFile(Base):
    __tablename__ = "submission_files"

    id: Mapped[int] = mapped_column(primary_key=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey("submissions.id"), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    path: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    mime: Mapped[str] = mapped_column(String(128), nullable=False)

    submission: Mapped[Submission] = relationship(back_populates="files")


class MarkConfidence(str, enum.Enum):
    high = "high"
    medium = "medium"
    low = "low"
    # The AI never proposes marks without an official mark scheme.
    tutor_only = "tutor_only"


class QuestionMark(Base):
    __tablename__ = "question_marks"
    __table_args__ = (UniqueConstraint("submission_id", "question_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey("submissions.id"), nullable=False)
    question_id: Mapped[int] = mapped_column(ForeignKey("assignment_questions.id"), nullable=False)
    ai_transcription: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_marks: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ai_feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_confidence: Mapped[MarkConfidence | None] = mapped_column(
        Enum(MarkConfidence, native_enum=False, length=16), nullable=True
    )
    # Which model and system-prompt version drafted this mark, so a bad mark
    # traces back to exactly what produced it (see services/prompts.py). Null
    # for marks drafted before AI output versioning.
    ai_model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ai_prompt_version: Mapped[str | None] = mapped_column(String(16), nullable=True)
    final_marks: Mapped[int | None] = mapped_column(Integer, nullable=True)
    final_feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    overridden: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    submission: Mapped[Submission] = relationship(back_populates="marks")
    question: Mapped[AssignmentQuestion] = relationship()


class JobStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    done = "done"
    failed = "failed"


class Job(TimestampMixin, Base):
    __tablename__ = "jobs"
    # The worker's claim query filters on exactly these two columns.
    __table_args__ = (Index("ix_jobs_status_run_after", "status", "run_after"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, native_enum=False, length=12), default=JobStatus.pending, nullable=False
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Earliest time the worker may claim this job; NULL means "as soon as
    # possible". Lets a caller schedule work into the future — used to
    # coalesce bursts of readiness recomputations into one run (see
    # readiness_v2_ai.enqueue_readiness_v2_debounced).
    run_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )
