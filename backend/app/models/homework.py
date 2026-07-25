import enum
from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
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
    # The AI marked every question confidently against an official mark
    # scheme: the marks count immediately and no tutor action is needed.
    auto_finalized = "auto_finalized"
    # At least one question the AI wasn't sure about (or a student has asked
    # for a remark) is waiting in the tutor's review queue.
    needs_review = "needs_review"
    # A tutor worked through the review queue and signed the submission off.
    finalized = "finalized"


class Submission(TimestampMixin, Base):
    """A student's uploaded answers to *either* a homework assignment or a past
    paper — exactly one of assignment_id / past_paper_id is set.

    Making this polymorphic rather than giving past papers their own table
    means SubmissionFile, QuestionMark, marking, the review queue, the override
    audit, remark requests and evidence-building all apply to past papers with
    no extra code."""

    __tablename__ = "submissions"
    __table_args__ = (
        UniqueConstraint("assignment_id", "student_id"),
        UniqueConstraint("past_paper_id", "student_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    assignment_id: Mapped[int | None] = mapped_column(
        ForeignKey("assignments.id"), nullable=True
    )
    past_paper_id: Mapped[int | None] = mapped_column(
        ForeignKey("past_papers.id"), nullable=True
    )
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    # Past papers only, and self-declared: the platform can't measure how long
    # a student took or whether they really sat it under timed conditions.
    timed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    time_taken_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    attempted_at: Mapped[date | None] = mapped_column(Date, nullable=True)
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

    assignment: Mapped[Assignment | None] = relationship()
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
    # No official mark scheme covered the question, so the AI marked it from
    # the syllabus and comparable questions. Always routed to a tutor.
    unsure = "unsure"
    # Legacy: what "unsure" was called when the AI refused to mark
    # scheme-less questions at all. Kept so old rows still read back.
    tutor_only = "tutor_only"


class QuestionMark(Base):
    """One question's mark within a submission. Exactly one of question_id
    (homework) / past_paper_question_id (past paper) is set, matching whichever
    kind of work the submission is for."""

    __tablename__ = "question_marks"
    __table_args__ = (
        UniqueConstraint("submission_id", "question_id"),
        UniqueConstraint("submission_id", "past_paper_question_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey("submissions.id"), nullable=False)
    question_id: Mapped[int | None] = mapped_column(
        ForeignKey("assignment_questions.id"), nullable=True
    )
    past_paper_question_id: Mapped[int | None] = mapped_column(
        ForeignKey("past_paper_questions.id"), nullable=True
    )
    # Set for homework marks; null for past-paper marks (which use
    # past_paper_question_id instead). Exactly one is set.
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
    # The AI wasn't confident enough for its mark to stand on its own (no
    # official mark-scheme coverage, or low confidence) — a tutor must look.
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # The AI's mark was accepted as final without a tutor touching it.
    auto_finalized: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    final_marks: Mapped[int | None] = mapped_column(Integer, nullable=True)
    final_feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    overridden: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    submission: Mapped[Submission] = relationship(back_populates="marks")
    question: Mapped[AssignmentQuestion | None] = relationship()


class MarkOverrideAudit(Base):
    """Append-only record of a tutor changing a mark that had already been
    set — whether overriding an auto-finalized AI mark or revising their own
    earlier decision. There is no API to edit or delete these: a mark dispute
    has to be answerable from the record months later."""

    __tablename__ = "mark_override_audit"

    id: Mapped[int] = mapped_column(primary_key=True)
    question_mark_id: Mapped[int] = mapped_column(ForeignKey("question_marks.id"), nullable=False)
    old_marks: Mapped[int | None] = mapped_column(Integer, nullable=True)
    new_marks: Mapped[int | None] = mapped_column(Integer, nullable=True)
    changed_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    # Free text; set to "remark_request" when the change resolves one.
    reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class RemarkRequestStatus(str, enum.Enum):
    open = "open"
    resolved = "resolved"


class RemarkRequest(Base):
    """A student contesting a finalized mark. Never resolved by AI — it only
    routes the question into the tutor's review queue, with the AI's original
    reasoning shown for context. The unique constraint on question_mark_id
    enforces the one-open-request-per-question cap at the database level, so a
    resolved question cannot be re-contested."""

    __tablename__ = "remark_requests"
    __table_args__ = (UniqueConstraint("question_mark_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    question_mark_id: Mapped[int] = mapped_column(ForeignKey("question_marks.id"), nullable=False)
    requested_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[RemarkRequestStatus] = mapped_column(
        Enum(RemarkRequestStatus, native_enum=False, length=16),
        default=RemarkRequestStatus.open,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


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
