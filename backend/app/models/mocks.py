"""Mocks: an exam a tutor sets, a student sits, and the AI marks.

Deliberately independent of `Assignment` (AV-26, AV-115). A mock is not
homework with a flag on it — it is set, sat and marked on its own terms, and
the tutor's workflow for one has nothing to do with the other. That
independence is the product decision; the cost of it is the third arm on
`Submission` and `QuestionMark`, which is paid here rather than by bending
homework into a shape it is not.

`Assessment` (models/readiness.py) stays what it has always been: a mock or
test whose marks the tutor types in by hand. The two coexist because they are
two ways of recording the same kind of event — typed in, or sat and AI-marked —
and both write `EvidenceSource.mock`, so readiness weighs them identically. A
mock counts for what it is, not for how its marks were produced.
"""

import enum
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, utcnow
from app.models.readiness import AssessmentType


class MockStatus(str, enum.Enum):
    extracting = "extracting"
    extraction_failed = "extraction_failed"
    published = "published"
    closed = "closed"


class Mock(TimestampMixin, Base):
    """A paper a tutor sets for a group, sat by students and marked by the AI."""

    __tablename__ = "mocks"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    tutor_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"), nullable=False)
    # The group this mock is set for. Nullable so a tutor can upload and extract
    # a paper before deciding who sits it; students see nothing until it is set.
    group_id: Mapped[int | None] = mapped_column(ForeignKey("groups.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    # Reused rather than redeclared: AV-115 puts small tests, big tests and
    # mocks on the same tab, which is exactly the mock/test split `Assessment`
    # already draws. A second enum with the same two members would be a second
    # thing to keep in step.
    type: Mapped[AssessmentType] = mapped_column(
        Enum(AssessmentType, native_enum=False, length=8),
        default=AssessmentType.mock,
        nullable=False,
    )
    sat_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    # The question paper. Required — there is nothing to extract or mark without
    # it, unlike an Assignment, whose questions a tutor may type in by hand.
    paper_path: Mapped[str] = mapped_column(String(255), nullable=False)
    paper_name: Mapped[str] = mapped_column(String(255), nullable=False)
    paper_mime: Mapped[str] = mapped_column(String(128), nullable=False)
    # Optional, and the only thing that makes a mark from this paper eligible to
    # auto-finalize (AI-11, ADR-0009). A mock with no scheme still marks; every
    # mark lands in the tutor's queue instead.
    mark_scheme_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mark_scheme_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mark_scheme_mime: Mapped[str | None] = mapped_column(String(128), nullable=True)
    total_marks: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Task 3.6 measures against this; nothing reads it yet.
    duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[MockStatus] = mapped_column(
        Enum(MockStatus, native_enum=False, length=20),
        default=MockStatus.extracting,
        nullable=False,
    )
    extraction_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    questions: Mapped[list["MockQuestion"]] = relationship(
        back_populates="mock",
        cascade="all, delete-orphan",
        order_by="MockQuestion.position",
    )


class MockOpening(Base):
    """When one student first opened one mock — the moment its clock started.

    A row of its own rather than a column on `Submission`, because the clock has
    to start *before* there is a submission: a `Submission` is created when work
    is handed in, and by then the sitting is over. It is also the only honest
    place to record a student who opened the paper and never submitted.

    `AV-116` says the clock is server-side. A timer in the browser is a
    suggestion — the tab can be reloaded, the device clock moved, the page left
    open overnight — so `opened_at` is written here, by the server, once, and
    every remaining-time figure is computed from it.
    """

    __tablename__ = "mock_openings"
    # One opening per student per mock: the clock starts once and cannot be
    # restarted by closing the tab and coming back (`BE-6` — the endpoint is
    # idempotent, and this is what makes it true under a double-click too).
    __table_args__ = (UniqueConstraint("mock_id", "student_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    mock_id: Mapped[int] = mapped_column(ForeignKey("mocks.id"), nullable=False)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class MockQuestion(Base):
    __tablename__ = "mock_questions"
    __table_args__ = (UniqueConstraint("mock_id", "number"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    mock_id: Mapped[int] = mapped_column(ForeignKey("mocks.id"), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    number: Mapped[str] = mapped_column(String(16), nullable=False)
    text_summary: Mapped[str] = mapped_column(Text, nullable=False)
    max_marks: Mapped[int] = mapped_column(Integer, nullable=False)
    has_mark_scheme: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    ai_model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ai_prompt_version: Mapped[str | None] = mapped_column(String(16), nullable=True)

    mock: Mapped[Mock] = relationship(back_populates="questions")
    topics: Mapped[list["MockQuestionTopic"]] = relationship(
        back_populates="question", cascade="all, delete-orphan"
    )


class MockQuestionTopic(Base):
    __tablename__ = "mock_question_topics"
    __table_args__ = (UniqueConstraint("question_id", "topic_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("mock_questions.id"), nullable=False)
    topic_id: Mapped[int] = mapped_column(ForeignKey("topics.id"), nullable=False)

    question: Mapped[MockQuestion] = relationship(back_populates="topics")
