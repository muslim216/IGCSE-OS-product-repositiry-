"""The permanent record of an attempt a tutor let a student redo."""

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, utcnow


class AttemptRedo(Base):
    """One attempt a tutor set aside so the student could hand the work in again.

    **Append-only. There is no API to edit or delete a row** (`PROD-7`): what a
    tutor did to a student's marks has to be answerable from the record months
    later, the same promise `MarkOverrideAudit` makes.

    The old attempt is *moved* here, not flagged. `record` is a complete
    snapshot of the submission, its files, its question marks, their override
    audit and remark requests, and the mistakes tagged on them; the live rows
    are then deleted, so nothing that reads submissions, marks, mistakes or
    evidence can still count it and no reader needs a new filter. The only
    thing that decides what counts toward readiness is whether the row exists.

    **Why the override audit rows are carried here rather than left where they
    were.** `mark_override_audit.question_mark_id` is a foreign key with no
    cascade, and the marks it points at are exactly what is being removed. Left
    in place, the audit would either block the delete or dangle. The audit's
    purpose — a mark dispute answerable from the record months later — is kept
    by carrying every row verbatim into a record that is itself append-only.

    `previous_submission_id` is a plain integer, not a foreign key, for the
    reason `MistakeRevisionAudit`'s ids are: the row it names no longer
    exists, so a real key would either forbid the delete or fail on Postgres
    while passing on a SQLite suite that runs with foreign keys off (`RISK-3`).

    `previous_final_marks` / `previous_max_marks` total only the questions that
    had a final mark, both on the same set so the pair is a fair fraction. Both
    are NULL when no question had one — never 0, which would say "scored
    nothing" about work nobody finished marking (`PROD-2`).
    """

    __tablename__ = "attempt_redos"
    # Declared here as well as in migration 0071 so the test schema matches
    # production (`DB-12`).
    __table_args__ = (
        Index("ix_attempt_redos_organization_id", "organization_id"),
        Index("ix_attempt_redos_student_id", "student_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    work_id: Mapped[int] = mapped_column(ForeignKey("assessable_work.id"), nullable=False)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    allowed_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    previous_submission_id: Mapped[int] = mapped_column(Integer, nullable=False)
    previous_final_marks: Mapped[int | None] = mapped_column(Integer, nullable=True)
    previous_max_marks: Mapped[int | None] = mapped_column(Integer, nullable=True)
    record: Mapped[dict] = mapped_column(JSON, nullable=False)
