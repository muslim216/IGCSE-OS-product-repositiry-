"""Assessable work: one parent row per homework/past-paper/mock instance.

`organization_id` and `subject_id` are copied here from the child (for an
assignment, from its Group, which is where an assignment's org and subject
actually live) rather than looked up through it. That duplication is the
point: five cross-kind queries currently OR three separate `organization_id`
columns together, and a missed arm fails silently. One column here replaces
that OR.

Every assignment, past paper and mock has one of these since `0047`, and their
`work_id` is NOT NULL — so a piece of work without a parent cannot be written.
Make the pair through `services/work.create_work`, never a child on its own.
The cross-kind queries still read the three child tables; moving them onto this
one is D4 and D5.
"""

import enum

from sqlalchemy import Enum, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class WorkKind(str, enum.Enum):
    homework = "homework"
    past_paper = "past_paper"
    mock = "mock"


class AssessableWork(TimestampMixin, Base):
    __tablename__ = "assessable_work"
    # Composite, though every consumer named today — the review queue, the home
    # count, the activity feed — filters `organization_id` alone. The second
    # column is a bet on the student-visible listings, which must be scoped by
    # (organization, subject) and never subject alone (`SEC-8`). It is a cheap
    # bet: a btree serves a leading-prefix lookup, so the org-only queries pay
    # nothing for it. If nothing ends up filtering subject, drop the column from
    # the index — it is a performance choice, reversible in one migration.
    __table_args__ = (
        Index("ix_assessable_work_organization_id_subject_id", "organization_id", "subject_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"), nullable=False)
    kind: Mapped[WorkKind] = mapped_column(
        Enum(WorkKind, native_enum=False, length=16), nullable=False
    )
    # Nullable: a past paper has no title until AI extraction reads it off the
    # document, and `PROD-2` forbids inventing one to fill the gap.
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
