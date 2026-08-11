import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, utcnow


class NarrativeAudience(str, enum.Enum):
    tutor_class = "tutor_class"
    parent_student = "parent_student"


class Narrative(Base):
    """A precomputed, stored plain-prose paragraph about a class (for the tutor)
    or a child (for the parent).

    Append-only: a refresh writes a new row and the read takes the latest, so a
    surface never blocks on a live model call to render its primary content, and
    a regeneration never blanks the previous text mid-flight (UX-21).

    `group_id` and `student_id` are two nullable FKs selected by `audience` —
    structurally identical to Submission.assignment_id/past_paper_id, which
    API-20 exists to guard because reading the wrong one raises *inside* an
    authorization check and would attach a paragraph about one child to another
    child's parent. So no caller reads either FK directly: they go through
    `target_id` below, the one place the audience/FK pairing is enforced.

    No `reviewed_at` and no `suppressed` column — there is no review step (D2).
    Adding them "just in case" would invite a workflow to grow around them.
    """

    __tablename__ = "narratives"
    __table_args__ = (
        # Every FK gets the tenant-filter index.
        Index("ix_narratives_org", "organization_id"),
        # "latest tutor_class narrative for a group" and "...parent_student for a
        # student". Ordered by id, not generated_at: a manual Prepare-again
        # racing the weekly sweep can write two rows with equal or out-of-order
        # generated_at, and id is the only column that totally orders insertion.
        # Postgres scans this ascending index backwards for the DESC read, so it
        # serves "latest for this target" without a separate DESC index.
        Index("ix_narratives_org_group", "organization_id", "group_id", "id"),
        Index("ix_narratives_org_student", "organization_id", "student_id", "id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    audience: Mapped[NarrativeAudience] = mapped_column(
        Enum(NarrativeAudience, native_enum=False, length=16), nullable=False
    )
    group_id: Mapped[int | None] = mapped_column(ForeignKey("groups.id"), nullable=True)
    student_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    # Which services/prompts.py version wrote this text, so a bad narrative traces
    # to the exact prompt behind it (AI-7).
    prompt_version: Mapped[str] = mapped_column(String(16), nullable=False)
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    # Timezone-aware on purpose: 0012_organizations.py carries the scar of a naive
    # column compiling to TIMESTAMP WITHOUT TIME ZONE, which asyncpg then rejects
    # a tz-aware bind against.
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    @property
    def target_id(self) -> int:
        """The id this narrative is about, chosen by `audience`. The single place
        a polymorphic FK is read — every caller goes through here, so the
        audience/FK pairing is enforced in exactly one spot (API-20)."""
        if self.audience is NarrativeAudience.tutor_class:
            if self.group_id is None:
                raise ValueError("tutor_class narrative has no group_id")
            return self.group_id
        if self.audience is NarrativeAudience.parent_student:
            if self.student_id is None:
                raise ValueError("parent_student narrative has no student_id")
            return self.student_id
        raise ValueError(f"unhandled narrative audience {self.audience!r}")
