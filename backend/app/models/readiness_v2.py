"""Readiness Engine v2 — two layers.

Layer 1 (deterministic, explainable): FactorEvaluation rows, one per factor
per computation run, computed by pure Python from stored evidence (mistakes,
past paper attempts, homework/assessment marks, lesson-topic coverage).
Never updated after insert — a historical AI synthesis must always be
reconstructable from the exact FactorEvaluation rows it was built from.

Layer 2 (AI synthesis): ReadinessSnapshot is the final result for one
(student, subject) computation run, produced from the run's FactorEvaluation
rows + the org's ReadinessWeights. Every snapshot carries the
evaluation_run_id linking it back to its deterministic inputs, and an
explicit status so an AI failure still preserves the deterministic layer
instead of losing the whole evaluation.

Supersedes TutorPreferences (-> ReadinessWeights) and
TopicReadiness/ReadinessHistory (-> ReadinessSnapshot + FactorEvaluation).
"""

import enum
from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, utcnow


class MistakeCategory(str, enum.Enum):
    misread = "misread"
    content_gap = "content_gap"
    careless = "careless"
    calculation = "calculation"
    time_management = "time_management"


class Mistake(TimestampMixin, Base):
    """An AI-tagged, tutor-confirmable recurring-mistake record for one
    marked question. Feeds the Mistake Analysis readiness factor."""

    __tablename__ = "mistakes"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    question_mark_id: Mapped[int] = mapped_column(ForeignKey("question_marks.id"), nullable=False)
    topic_id: Mapped[int | None] = mapped_column(ForeignKey("topics.id"), nullable=True)
    category: Mapped[MistakeCategory] = mapped_column(
        Enum(MistakeCategory, native_enum=False, length=16), nullable=False
    )
    severity: Mapped[int] = mapped_column(
        Integer, default=1, nullable=False
    )  # 1 (minor) .. 3 (major)
    confirmed_by_tutor: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class PastPaper(TimestampMixin, Base):
    """A full past paper a tutor uploads once and every student can attempt.

    Distinct from a classified (see CLAUDE.md): a classified is a topic-compiled
    selection of questions, a past paper is the whole thing, sat under timed
    conditions and marked against the official scheme. It carries files like a
    Classified does, and rides the same extract -> mark -> review pipeline, but
    the mark scheme is REQUIRED — a paper's marks feed the Past Paper
    Performance factor, so they may not rest on the AI's judgement alone."""

    __tablename__ = "past_papers"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    tutor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"), nullable=False)
    # The paper's own name, read off the document by extraction — never typed
    # by the tutor. e.g. "Cambridge IGCSE Physics 0625/41 Paper 4 Theory
    # (Extended) October/November 2026". Null until extraction has run; see
    # `display_title` for what every call site actually renders (PROD-2).
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # AI-filled from the document alongside `title` — the tutor no longer
    # types either. Null until extraction runs.
    session_label: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )  # e.g. "November 2026"
    paper_number: Mapped[str | None] = mapped_column(String(32), nullable=True)  # e.g. "Paper 1"
    total_marks: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # How long the real exam allows, so a student's self-declared time_taken
    # means something.
    duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # The question booklet. Nullable only because rows created before past
    # papers had files (seed/demo data) still exist.
    booklet_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    booklet_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    booklet_mime: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # The official mark scheme — required at upload, tutor-only to download.
    mark_scheme_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mark_scheme_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mark_scheme_mime: Mapped[str | None] = mapped_column(String(128), nullable=True)
    extraction_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    @property
    def display_title(self) -> str:
        """The name every site actually shows for this paper. AI-filled from
        the document once extraction runs; "Untitled paper" until then or if
        extraction never produced one — never the tutor's old typed guess
        (`PROD-2`: absent data is shown as absent, not fabricated)."""
        return self.title or "Untitled paper"


class PastPaperQuestion(Base):
    """One question extracted from a past paper booklet. Mirrors
    AssignmentQuestion so the same marking prompt and review UI apply."""

    __tablename__ = "past_paper_questions"
    __table_args__ = (UniqueConstraint("past_paper_id", "number"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    past_paper_id: Mapped[int] = mapped_column(ForeignKey("past_papers.id"), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    number: Mapped[str] = mapped_column(String(16), nullable=False)
    text_summary: Mapped[str] = mapped_column(Text, nullable=False)
    max_marks: Mapped[int] = mapped_column(Integer, nullable=False)
    has_mark_scheme: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Which model and prompt version extracted this question (see
    # services/prompts.py), so a bad extraction is traceable.
    ai_model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ai_prompt_version: Mapped[str | None] = mapped_column(String(16), nullable=True)


class PastPaperQuestionTopic(Base):
    __tablename__ = "past_paper_question_topics"
    __table_args__ = (UniqueConstraint("question_id", "topic_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("past_paper_questions.id"), nullable=False)
    topic_id: Mapped[int] = mapped_column(ForeignKey("topics.id"), nullable=False)


class PastPaperAttempt(TimestampMixin, Base):
    """The finalized roll-up of one student's attempt — what the Past Paper
    Performance factor reads. The per-question detail lives on the Submission
    that produced it; raw_marks is filled in when that submission settles."""

    __tablename__ = "past_paper_attempts"

    id: Mapped[int] = mapped_column(primary_key=True)
    past_paper_id: Mapped[int] = mapped_column(ForeignKey("past_papers.id"), nullable=False)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    raw_marks: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_marks: Mapped[int] = mapped_column(Integer, nullable=False)
    # Self-declared by the student: the platform cannot observe either of these.
    timed: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    time_taken_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    attempted_at: Mapped[date] = mapped_column(Date, nullable=False)


class GradeBoundary(Base):
    """Per-organization grade boundaries, entered by the tutor per subject and
    editable in Settings.

    **The only source of a predicted grade** since task 2.4 (`AV-11`): the
    `Subject.grade_boundaries` column this used to override is dropped, and a
    subject with no rows here has no predicted grade anywhere rather than one
    mapped through a shipped default (`PROD-2`, `PROD-6`).

    Org-scoped, not subject-scoped, because two tutors in one organization share
    these numbers and no tenant may ever move another's (`SEC-8`)."""

    __tablename__ = "grade_boundaries"
    __table_args__ = (UniqueConstraint("organization_id", "subject_id", "grade_label"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"), nullable=False)
    grade_label: Mapped[str] = mapped_column(String(16), nullable=False)
    min_percentage: Mapped[float] = mapped_column(Float, nullable=False)


class ReadinessWeights(TimestampMixin, Base):
    """Supersedes TutorPreferences — one weight per readiness factor (not
    per evidence source), plus the decay half-life as an advanced setting."""

    __tablename__ = "readiness_weights"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id"), nullable=False, unique=True
    )
    tutor_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    weight_topic_mastery: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    weight_past_paper_performance: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    weight_homework_performance: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    weight_assessment_performance: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    weight_syllabus_coverage: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    weight_mistake_analysis: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    weight_consistency: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    half_life_days: Mapped[float] = mapped_column(Float, default=45.0, nullable=False)


class ReadinessFactor(str, enum.Enum):
    topic_mastery = "topic_mastery"
    past_paper_performance = "past_paper_performance"
    homework_performance = "homework_performance"
    assessment_performance = "assessment_performance"
    syllabus_coverage = "syllabus_coverage"
    mistake_analysis = "mistake_analysis"
    consistency = "consistency"


class FactorConfidence(str, enum.Enum):
    no_data = "no_data"
    low = "low"
    medium = "medium"
    high = "high"


class FactorEvaluation(Base):
    """One deterministic factor's sub-score for one computation run.
    Append-only: never updated, only ever inserted, so the exact inputs
    behind any historical AI synthesis stay reconstructable."""

    __tablename__ = "factor_evaluations"

    # Declared here as well as in migration 0016_readiness_v2_schema.py — the test schema is built
    # from `Base.metadata`, so an index that lives only in a migration makes the
    # suite run against a different shape than production (`DB-12`).
    __table_args__ = (
        Index(
            "ix_factor_evaluations_run_student_subject",
            "evaluation_run_id",
            "student_id",
            "subject_id",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    evaluation_run_id: Mapped[str] = mapped_column(String(36), nullable=False)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"), nullable=False)
    # Set for topic-level factors (Topic Mastery); null for subject-level ones.
    topic_id: Mapped[int | None] = mapped_column(ForeignKey("topics.id"), nullable=True)
    factor: Mapped[ReadinessFactor] = mapped_column(
        Enum(ReadinessFactor, native_enum=False, length=32), nullable=False
    )
    score: Mapped[float | None] = mapped_column(Float, nullable=True)  # None = no data
    confidence: Mapped[FactorConfidence] = mapped_column(
        Enum(FactorConfidence, native_enum=False, length=8), nullable=False
    )
    evidence_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    detail: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class AiSynthesisStatus(str, enum.Enum):
    ready = "ready"
    failed = "failed"


class ReadinessSnapshot(Base):
    """The final, AI-synthesized readiness result for one (student, subject)
    computation run — supersedes TopicReadiness + ReadinessHistory. Carries
    the evaluation_run_id linking it to the exact FactorEvaluation rows it
    was synthesized from. When the AI call fails, a row is still written
    with status='failed' so the deterministic layer isn't lost. Append-only."""

    __tablename__ = "readiness_snapshots"

    # Declared here as well as in migration 0016_readiness_v2_schema.py — the test schema is built
    # from `Base.metadata`, so an index that lives only in a migration makes the
    # suite run against a different shape than production (`DB-12`).
    __table_args__ = (
        Index(
            "ix_readiness_snapshots_student_subject",
            "student_id",
            "subject_id",
            "created_at",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    evaluation_run_id: Mapped[str] = mapped_column(String(36), nullable=False)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"), nullable=False)
    status: Mapped[AiSynthesisStatus] = mapped_column(
        Enum(AiSynthesisStatus, native_enum=False, length=8), nullable=False
    )
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    predicted_grade: Mapped[str | None] = mapped_column(String(16), nullable=True)
    weak_topics: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    recommended_revision: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
