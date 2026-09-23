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
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, utcnow


class MistakeCategory(TimestampMixin, Base):
    """A kind of mistake, named by the tutor who teaches the subject.

    This was a five-member enum. It is a table because the words a tutor uses
    for what went wrong are theirs: "careless" is not a category every subject
    or every teacher recognises, and a fixed list quietly tells a tutor their
    vocabulary is wrong.

    **Nothing may branch on a category's value.** No `if name == "careless"`.
    The contents are tutor data, so code that reads meaning into them breaks
    the moment someone renames one — silently, because a rename is a valid
    edit and nothing would fail.

    Scoped per (organization, subject) like GradeBoundary, for the same reason:
    a subject is owned by one tenant, but tutors sharing an organization share
    its setup, and no tenant may ever see another's (SEC-8).
    """

    __tablename__ = "mistake_categories"
    __table_args__ = (
        # Unique on the folded name, not the name as typed. The editor and
        # `save_categories` both treat "Careless" and "careless" as one
        # category, so a database that does not would let two saves landing at
        # once create both — after which the editor reads its own stored list
        # as a duplicate and refuses to save anything at all, with nothing the
        # tutor can do about it from the screen (cubic). Declared here as well
        # as created in the migration (`DB-12`).
        Index(
            "uq_mistake_categories_org_subject_lower_name",
            "organization_id",
            "subject_id",
            text("lower(name)"),
            unique=True,
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(60), nullable=False)
    # Written for the model to read, not only the tutor: 4.2 passes this list
    # into the tagging prompt, and a bare word like "careless" is ambiguous to
    # anything that has not sat in the room.
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Archived, never deleted — mistakes already tagged with it must keep
    # reading back. An archived category is hidden from new tagging and from
    # the editor's live list, and nothing else about it changes.
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MistakeSource(str, enum.Enum):
    """Who decided this mistake — the tagging job, or a tutor.

    Load-bearing, not descriptive. `tag_mistakes` re-runs on the same
    submission whenever marks change or a tutor presses re-tag, and it must
    replace what it wrote last time without touching what a tutor decided.
    "Delete the rows I made" is only expressible if a row says who made it
    (decision 8, E17).
    """

    ai = "ai"
    tutor = "tutor"


class MistakeTopic(Base):
    """Which topics the question behind a mistake tests.

    A link table rather than `Mistake.topic_id`, because a question carries
    many topics — `QuestionTopic` is unique on (question_id, topic_id) and the
    extractor returns a list. The single column meant a multi-topic question
    was recorded against one topic chosen arbitrarily, or skipped; decision 11
    says every topic, never a skip.

    No `TimestampMixin`: a link either holds or it does not, and the mistake it
    hangs off already carries when it was made.
    """

    __tablename__ = "mistake_topics"
    __table_args__ = (
        UniqueConstraint("mistake_id", "topic_id", name="uq_mistake_topics_mistake_id_topic_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    mistake_id: Mapped[int] = mapped_column(ForeignKey("mistakes.id"), nullable=False)
    topic_id: Mapped[int] = mapped_column(ForeignKey("topics.id"), nullable=False)


class Mistake(TimestampMixin, Base):
    """An AI-tagged, tutor-confirmable recurring-mistake record for one
    marked question. Feeds the Mistake Analysis readiness factor."""

    __tablename__ = "mistakes"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Both indexed, and declared here as well as in the migration (`DB-12`) —
    # four of this schema's five existing indexes live only in a migration, so
    # the test schema, built from `Base.metadata`, silently differs from
    # production. `student_id` carries the readiness read
    # (`readiness_v2._mistake_points_and_analysed`, run on every recompute);
    # `question_mark_id` carries both delete paths — this job's own
    # `_delete_own_mistakes` and `attempts.open_attempt`'s resubmission cleanup.
    # `category_id` is left unindexed: it is only ever joined to
    # `mistake_categories.id` after `student_id` has already cut the rows down.
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    question_mark_id: Mapped[int] = mapped_column(
        ForeignKey("question_marks.id"), nullable=False, index=True
    )
    category_id: Mapped[int] = mapped_column(ForeignKey("mistake_categories.id"), nullable=False)
    severity: Mapped[int] = mapped_column(
        Integer, default=1, nullable=False
    )  # 1 (minor) .. 3 (major)
    confirmed_by_tutor: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Who decided this mistake. The tagging job deletes its own rows and only
    # its own before re-inserting, so this is the whole of E17's enforcement.
    source: Mapped[MistakeSource] = mapped_column(
        Enum(MistakeSource, native_enum=False, length=8), nullable=False
    )
    # What the tagging job saw when a category's name/description or a
    # question's ai_feedback read like an instruction rather than data — the
    # SEC-20 flag-rather-than-obey half. Resisting an injection silently is
    # not enough, since nothing else in this pipeline reads these rows before
    # a tutor does; this is where the model records what it saw so a tutor
    # can. Null on every ordinary tag. Only `services/mistake_tagging.py`
    # writes it.
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class MistakeRevisionAudit(Base):
    """Append-only record of a tutor changing a mistake the AI tagged.

    A revision is a tutor override of AI output, so it leaves the same kind of
    trail `MarkOverrideAudit` leaves for a mark: no API edits or deletes one,
    because "why is this tagged careless" has to be answerable months later
    (`PROD-7`, `AI-12`).

    A sibling table rather than a reuse of `mark_override_audit`: that one
    records a mark moving between two integers, this one records a category
    and a severity moving together. Widening it with four nullable columns
    would make every row of both kinds half-empty and leave nothing in the
    schema saying which half is meaningful.

    **Every id here is a plain integer, including `mistake_id`.** Not a
    ForeignKey, for the reason an audit row exists at all: it must outlive
    what it describes. `attempts.open_attempt` hard-deletes a submission's
    `Mistake` rows when a student replaces the work, so a real FK would make a
    resubmission fail on any database that enforces one — the suite runs
    SQLite with foreign keys *off*, so it would have passed here and broken on
    production Postgres, which is exactly the shape `RISK-3` records as
    already having happened. Cascading instead would delete the record of the
    tutor's decision, which `PROD-7` is the reason not to.

    The category name is not stored alongside its id: a rename is a valid edit
    and the current name is what the tutor means today (see MistakeCategory).
    """

    __tablename__ = "mistake_revision_audit"

    # Declared here as well as in migration 0053 (`DB-12`) — the test schema is
    # built from `Base.metadata`, so an index living only in the migration
    # makes the suite run against a different shape than production.
    __table_args__ = (Index("ix_mistake_revision_audit_mistake_id", "mistake_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    mistake_id: Mapped[int] = mapped_column(Integer, nullable=False)
    old_category_id: Mapped[int] = mapped_column(Integer, nullable=False)
    new_category_id: Mapped[int] = mapped_column(Integer, nullable=False)
    old_severity: Mapped[int] = mapped_column(Integer, nullable=False)
    new_severity: Mapped[int] = mapped_column(Integer, nullable=False)
    changed_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class PastPaper(TimestampMixin, Base):
    """A full past paper a tutor uploads once and every student can attempt.

    Distinct from a classified (see CLAUDE.md): a classified is a topic-compiled
    selection of questions, a past paper is the whole thing, sat under timed
    conditions and marked against the official scheme. It carries files like a
    Classified does, and rides the same extract -> mark -> review pipeline.

    The mark scheme used to be required here, on the grounds that a paper's
    marks feed the Past Paper Performance factor and so may not rest on the
    AI's judgement alone. The product owner reversed that in task 3.5: a tutor
    who has the paper but not the scheme could otherwise upload nothing. The
    guarantee is unchanged, because the scheme was never what enforced it —
    `scheme_backed()` in `services/marking.py` is, and with no scheme attached
    it auto-finalizes nothing, so every mark waits for the tutor (`AI-11`,
    `ADR-0009`)."""

    __tablename__ = "past_papers"
    # `booklet_index` is what makes approving a booklet safe to re-run (`BE-6`).
    # Delivery is at-least-once and a worker that dies mid-approve is requeued,
    # so the handler can meet a booklet whose papers it already half-created.
    # Without a natural key it would insert them a second time; with one the
    # re-run collides and can skip. It doubles as the index every paper list
    # needs, since `booklet_id` leads it — a separate index on `booklet_id`
    # alone would be redundant (`DB-12`).
    __table_args__ = (UniqueConstraint("booklet_id", "booklet_index"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    # NOT NULL: every past paper belongs to exactly one booklet, a single upload
    # included — that becomes a booklet of one. A paper with no parent would have
    # nowhere to keep its file, its scheme or its extraction status.
    booklet_id: Mapped[int] = mapped_column(ForeignKey("booklets.id"), nullable=False)
    # Which paper of its booklet this is, counting from 1. A booklet of one
    # always holds a single paper at 1.
    booklet_index: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    # Which pages of the booklet this paper was cut from, for provenance: a
    # mis-split is otherwise only fixable by re-uploading, and nothing can say
    # "pages 12-23 of this booklet" (`PROD-1`).
    #
    # NULL means the whole document, which is the booklet-of-one case. It is
    # deliberately not filled in with 1..page_count there: knowing the page
    # count means parsing the PDF, and that is a blocking CPU-bound call in a
    # request handler (`BE-13`, `PERF-1`). Absent rather than computed.
    first_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
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
    # The question paper. Nullable only because rows created before past
    # papers had files (seed/demo data) still exist.
    paper_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    paper_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    paper_mime: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # The official mark scheme — optional since task 3.5, tutor-only to
    # download. NULL means nothing from this paper auto-finalizes.
    mark_scheme_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mark_scheme_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mark_scheme_mime: Mapped[str | None] = mapped_column(String(128), nullable=True)
    extraction_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # When the tutor took this paper off their own shelf. It stays visible to
    # every student who can already see it, which is the product owner's
    # decision and not an oversight: a student mid-attempt, or one looking back
    # at a paper they sat, must not have it vanish under them. So this hides a
    # row from one list, and is deliberately not a delete — a delete would take
    # the attempts, the marks and the evidence built on them with it.
    #
    # A timestamp rather than a boolean because "when" is the question a tutor
    # asks when a paper they expected is missing, and `IS NULL` filters exactly
    # as well as `= false`.
    hidden_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    work_id: Mapped[int] = mapped_column(
        ForeignKey("assessable_work.id"), nullable=False, unique=True
    )

    @property
    def display_title(self) -> str:
        """The name every site actually shows for this paper. AI-filled from
        the document once extraction runs; "Untitled paper" until then or if
        extraction never produced one — never the tutor's old typed guess
        (`PROD-2`: absent data is shown as absent, not fabricated)."""
        return self.title or "Untitled paper"


class PastPaperQuestion(Base):
    """One question extracted from a past paper. Mirrors
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
    half_life_days: Mapped[float] = mapped_column(Float, default=45.0, nullable=False)


class ReadinessFactor(str, enum.Enum):
    topic_mastery = "topic_mastery"
    past_paper_performance = "past_paper_performance"
    homework_performance = "homework_performance"
    assessment_performance = "assessment_performance"
    syllabus_coverage = "syllabus_coverage"
    mistake_analysis = "mistake_analysis"
    # Retired by AV-30 (task 5.1): never written by the engine any more. Kept
    # only because factor_evaluations is append-only and holds historical runs
    # with this value — removing the member makes SQLAlchemy raise LookupError
    # loading them (non-native enum, DB-5). Do not reuse the name.
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
