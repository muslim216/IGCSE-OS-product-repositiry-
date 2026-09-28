"""Tutor-defined criteria and the scores a tutor hands each student on them.

Shown beside readiness, never inside it. There is deliberately no weight
column, and nothing in the readiness engine or its synthesis prompt reads these
tables: a hand-entered 0-100 has no evidence behind it, so letting it move a
score the product calls traceable would break `PROD-1`.
"""

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, utcnow


class CustomCriterion(TimestampMixin, Base):
    """A thing a tutor wants to score students on, e.g. "Exam technique".

    `subject_id` NULL means the criterion applies to every subject. It is fixed
    at creation: a score was given against the scope the criterion had then,
    and moving the criterion to another subject would silently re-home every
    score onto students it was never meant for. Archived, never deleted, so the
    scores and their audit trail keep something to point at.
    """

    __tablename__ = "custom_criteria"
    # Declared here as well as in migration 0058 (`DB-12`).
    __table_args__ = (Index("ix_custom_criteria_organization_id", "organization_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    subject_id: Mapped[int | None] = mapped_column(ForeignKey("subjects.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)


class CustomCriterionScore(Base):
    """One student's current score on one criterion. No row means unscored —
    absent, never 0 (`PROD-2`). Clearing a score deletes the row; the audit
    table is what remembers it existed."""

    __tablename__ = "custom_criterion_scores"
    __table_args__ = (
        UniqueConstraint(
            "student_id", "criterion_id", name="uq_custom_criterion_scores_student_id_criterion_id"
        ),
        CheckConstraint(
            "score >= 0 AND score <= 100", name="ck_custom_criterion_scores_score_range"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    criterion_id: Mapped[int] = mapped_column(ForeignKey("custom_criteria.id"), nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)


class CustomCriterionScoreAudit(Base):
    """Append-only record of a tutor setting, changing or clearing a score.

    Every score is a tutor judgement with no evidence behind it, so "who said
    this student's exam technique was 40, and when" has to stay answerable
    after the score moves on (`PROD-7`). No API edits or deletes one.
    `new_score` NULL means the score was cleared; `old_score` NULL means there
    was none before.

    **Every id here is a plain integer.** Not a ForeignKey, for the reason an
    audit row exists at all: it must outlive what it describes. Clearing a
    score deletes its `custom_criterion_scores` row, and nothing promises a
    criterion or a user is never removed; a real FK would make any such delete
    fail on a database that enforces one — the suite runs SQLite with foreign
    keys *off*, so it would pass here and break on production Postgres, which
    is exactly the shape `RISK-3` records as already having happened.
    Cascading instead would delete the record of the tutor's decision, which
    `PROD-7` is the reason not to.
    """

    __tablename__ = "custom_criterion_score_audit"
    # Declared here as well as in migration 0058 (`DB-12`). Every read is
    # "what happened to this student's score on this criterion".
    __table_args__ = (
        Index(
            "ix_custom_criterion_score_audit_student_id_criterion_id",
            "student_id",
            "criterion_id",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(Integer, nullable=False)
    student_id: Mapped[int] = mapped_column(Integer, nullable=False)
    criterion_id: Mapped[int] = mapped_column(Integer, nullable=False)
    old_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    new_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    changed_by_id: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
