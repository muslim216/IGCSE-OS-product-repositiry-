import enum
from datetime import datetime

from sqlalchemy import (
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, utcnow


class EvidenceSource(str, enum.Enum):
    homework = "homework"
    quiz = "quiz"
    mock = "mock"
    observation = "observation"


class Evidence(Base):
    """Append-only record of one piece of academic evidence about a student on a
    topic. Everything the Readiness Engine computes is derived from these rows,
    so every score is explainable by listing its contributing evidence."""

    __tablename__ = "evidence"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    topic_id: Mapped[int] = mapped_column(ForeignKey("topics.id"), nullable=False)
    source_type: Mapped[EvidenceSource] = mapped_column(
        Enum(EvidenceSource, native_enum=False, length=16), nullable=False
    )
    score_pct: Mapped[float] = mapped_column(Float, nullable=False)  # 0..100
    max_marks: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    # Where this came from, e.g. "submission:42" or "assessment:7" — for drill-down.
    source_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    label: Mapped[str | None] = mapped_column(String(255), nullable=True)


class ReadinessConfidence(str, enum.Enum):
    none = "none"
    low = "low"
    medium = "medium"
    high = "high"


class TopicReadiness(Base):
    """Current readiness snapshot per (student, topic). Recomputed from evidence."""

    __tablename__ = "topic_readiness"
    __table_args__ = (UniqueConstraint("student_id", "topic_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    topic_id: Mapped[int] = mapped_column(ForeignKey("topics.id"), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)  # 0..100
    confidence: Mapped[ReadinessConfidence] = mapped_column(
        Enum(ReadinessConfidence, native_enum=False, length=8), nullable=False
    )
    evidence_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class ReadinessHistory(Base):
    """Point-in-time subject readiness snapshots for trend charts."""

    __tablename__ = "readiness_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class TutorObservation(TimestampMixin, Base):
    """A tutor's qualitative note on a student, optionally tied to a topic and a
    0-100 rating that feeds readiness as observation evidence."""

    __tablename__ = "tutor_observations"

    id: Mapped[int] = mapped_column(primary_key=True)
    tutor_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    topic_id: Mapped[int | None] = mapped_column(ForeignKey("topics.id"), nullable=True)
    comment: Mapped[str] = mapped_column(Text, nullable=False)
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 0..100


class AssessmentType(str, enum.Enum):
    mock = "mock"
    test = "test"


class Assessment(TimestampMixin, Base):
    """A mock or test whose marks the tutor enters manually."""

    __tablename__ = "assessments"

    id: Mapped[int] = mapped_column(primary_key=True)
    tutor_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[AssessmentType] = mapped_column(
        Enum(AssessmentType, native_enum=False, length=8), default=AssessmentType.mock, nullable=False
    )
    date: Mapped[datetime] = mapped_column(Date, nullable=False)


class AssessmentScore(Base):
    __tablename__ = "assessment_scores"

    id: Mapped[int] = mapped_column(primary_key=True)
    assessment_id: Mapped[int] = mapped_column(ForeignKey("assessments.id"), nullable=False)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    # Null topic_id = overall subject score; otherwise a per-topic breakdown.
    topic_id: Mapped[int | None] = mapped_column(ForeignKey("topics.id"), nullable=True)
    marks: Mapped[int] = mapped_column(Integer, nullable=False)
    max_marks: Mapped[int] = mapped_column(Integer, nullable=False)
