import enum
from datetime import datetime

from sqlalchemy import (
    JSON,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class SubjectLevel(str, enum.Enum):
    """The qualification a subject is taught for (AV-7).

    Three levels, and nothing in the product may assume the IGCSE one. There is
    deliberately **no default**: a subject's level is the tutor's to state, and
    defaulting to `igcse` is precisely the assumption `AV-7` forbids.
    """

    igcse = "igcse"
    o_level = "o_level"
    a_level = "a_level"


class Subject(Base):
    __tablename__ = "subjects"
    # Was UniqueConstraint("exam_board", "code") — globally unique, because
    # subjects themselves were global. Two tutors may now each teach the same
    # specification, so identity is unique per tenant (AV-6, task 2.2). The
    # constraint doubles as the index for the organization filter every subject
    # query now carries, `organization_id` being its leading column.
    __table_args__ = (UniqueConstraint("organization_id", "exam_board", "code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    # PROD-3/DB-2: every top-level aggregate carries its tenant. A subject is
    # owned by the tutor who created it and is private to that account (AV-6);
    # before task 2.2 these were global rows shared by every organization.
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    exam_board: Mapped[str] = mapped_column(String(64), nullable=False)
    code: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    level: Mapped[SubjectLevel] = mapped_column(
        Enum(SubjectLevel, native_enum=False, length=16), nullable=False
    )
    # "9-1" (Edexcel IGCSE) or "A*-E" (Cambridge O Level)
    grade_scale: Mapped[str] = mapped_column(String(16), nullable=False)
    # The teaching guidance / scheme of work: the *second* per-subject setup
    # document (`AV-10`, task 2.5), beside the syllabus itself. Phase 6 reads it
    # to judge which chapters are harder or slower and weights the plan's time
    # accordingly (`AV-14`); nothing consumes it before then, so it is stored
    # and served, not parsed.
    #
    # Four nullable columns rather than a table: one document per subject,
    # replaced rather than versioned, with no processing state of its own — the
    # thing that makes `SyllabusUpload` a table. `guidance_path` is the object
    # key; the other three are what a download needs to be honest about what it
    # is handing back. All four are set and cleared together.
    guidance_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    guidance_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    guidance_mime: Mapped[str | None] = mapped_column(String(128), nullable=True)
    guidance_uploaded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # The tutor's own marking rules for this subject — the "AI marking
    # agreement" (`AV-75`, `AV-111`, task 2.6). Free text, in their words,
    # written once and applying to every chapter, classified and piece of work
    # in the subject. **In addition to** board, level and chapter notes, never
    # instead of them, and there is deliberately no account-wide layer (`AV-75`).
    #
    # Describes **how** the AI marks, never **when a mark counts** — `AV-25`'s
    # auto-finalize rule is untouched by whatever is written here.
    #
    # Phase 3's context assembler is what consumes it, under `AV-76`'s
    # precedence (mark scheme → chapter notes → subject rules → board and
    # level); nothing reads it before then. Nullable because it is the one
    # onboarding step a tutor may skip (`AV-87`).
    marking_rules: Mapped[str | None] = mapped_column(Text, nullable=True)
    # What the marking prompt is actually given (task 3.2c, owner's instruction:
    # the subject's rules are summarised and the AI uses the summary). The
    # tutor's full text above stays the thing they own and edit.
    #
    # Null is a working state, not a gap: `build_marking_context` falls back to
    # the full text when this is absent, so the window between a save and the
    # job finishing is correct rather than one in which the rules silently do
    # not apply. Writing `marking_rules` clears this in the same statement, so a
    # summary is absent or current, never stale — deliberately no fingerprint to
    # compare, because "clear and rebuild" cannot drift the way "compare and
    # decide" can.
    marking_rules_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    # No `grade_boundaries` column: task 2.4 (AV-11) made the org-scoped
    # `GradeBoundary` table the only source and migration 0031 dropped this one,
    # copying what it held into that table. Two sources that could disagree about
    # the same subject's grades were `RISK-5`; a subject with no rows there has
    # no predicted grade at all, which is the intended behaviour (PROD-2).

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
        # Redundant against the primary key, and there so `topics` can point a
        # composite foreign key at (subject_id, id) — which is what stops a topic
        # being filed under another subject's chapter. See Topic.__table_args__.
        UniqueConstraint("subject_id", "id", name="uq_chapters_subject_id_id"),
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
    # Read-only, on both sides. The composite foreign key shares `subject_id`
    # with `Subject.topics`, so a writable relationship here would give two of
    # them a claim on the same column and SQLAlchemy warns accordingly.
    # `Topic.subject` owns `subject_id`; a topic joins a chapter by setting
    # `chapter_id`, which is what the seed and migration 0029 both do.
    topics: Mapped[list["Topic"]] = relationship(viewonly=True, order_by="Topic.code")


class Topic(Base):
    __tablename__ = "topics"
    __table_args__ = (
        UniqueConstraint("subject_id", "code"),
        # Composite, not a plain FK on chapter_id alone: the chapter a topic
        # names must belong to the topic's own subject. A single-column FK
        # validates only that the chapter exists, so nothing would stop a topic
        # being filed under another subject's chapter — and a chapter rollup
        # would then quietly sum across subjects. `ADR-0010`'s whole argument for
        # a table over `parent_id` is making that class of mistake
        # unrepresentable rather than merely discouraged; this is the same
        # argument one level down.
        #
        # Both columns are in the constraint and `chapter_id` is nullable, so
        # default MATCH SIMPLE skips the check entirely while chapter_id is NULL
        # — which is exactly the "no chapter yet, until task 2.3" state.
        ForeignKeyConstraint(
            ["subject_id", "chapter_id"],
            ["chapters.subject_id", "chapters.id"],
            name="fk_topics_subject_id_chapter_id_chapters",
        ),
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
    # The foreign key lives in __table_args__ as a composite with subject_id.
    chapter_id: Mapped[int | None] = mapped_column(nullable=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("topics.id"), nullable=True)
    weight: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)

    subject: Mapped[Subject] = relationship(back_populates="topics")
    chapter: Mapped["Chapter | None"] = relationship(viewonly=True)


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
    # AI-drafted (and tutor-editable) syllabus data, validated by
    # `schemas.syllabus.SyllabusDraft`: exam_board, code, name, level,
    # grade_scale, grade_boundaries, topics. It used to be described as "the same
    # shape as seed/syllabus/*.json"; those files were the five built-in
    # syllabuses and task 2.2 deleted them (AV-8), so the schema is the shape now.
    draft: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    subject_id: Mapped[int | None] = mapped_column(ForeignKey("subjects.id"), nullable=True)
