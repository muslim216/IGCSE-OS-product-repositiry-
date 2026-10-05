"""Setup acknowledgements (task 9.1a): "the tutor looked at this default".

The only new storage onboarding needs. Whether a *Required* step is done is
derived from the rows that make it real (chapters, schedule slots, plans), and
whether a Defaulted value was changed is derived from what the code already
persists. This table holds the one fact nothing else can: the tutor saw a
default and chose to keep it.
"""

import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class SetupItem(str, enum.Enum):
    """The Defaulted setup items — the only ones that can be acknowledged.

    Required steps are never here (they are done or not, there is nothing to
    acknowledge) and neither is the Optional teaching guidance. Stored as a
    non-native enum (`DB-5`), so a new member needs no migration.
    """

    account_basics = "account_basics"
    boundaries = "boundaries"
    marking_rules = "marking_rules"
    mistake_categories = "mistake_categories"
    weak_threshold = "weak_threshold"


#: The one account-level item. Every other member is per subject.
ACCOUNT_ITEMS = frozenset({SetupItem.account_basics})


class SetupAcknowledgement(Base):
    __tablename__ = "setup_acknowledgements"
    __table_args__ = (
        # One acknowledgement per (organization, subject, item). Holds for the
        # per-subject rows only: Postgres and SQLite both treat NULLs as distinct
        # in a unique constraint, so two account-level rows (subject_id NULL)
        # would both pass it (RISK-3).
        UniqueConstraint(
            "organization_id",
            "subject_id",
            "item",
            name="uq_setup_acknowledgements_organization_id_subject_id_item",
        ),
        # What holds the account-level row to one, on both databases — the same
        # partial index `readiness_weights` uses for its NULL-subject row. A
        # sentinel subject_id of 0 would need a fake subject for the FK, and
        # COALESCE in an expression index is not portable to SQLite's batch
        # rebuilds. It is also what makes a concurrent double-submit safe: the
        # loser's INSERT fails and the service treats that as "already done".
        Index(
            "uq_setup_acknowledgements_account_item",
            "organization_id",
            "item",
            unique=True,
            postgresql_where=text("subject_id IS NULL"),
            sqlite_where=text("subject_id IS NULL"),
        ),
        Index("ix_setup_acknowledgements_org", "organization_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    # NULL for the account-level item.
    subject_id: Mapped[int | None] = mapped_column(ForeignKey("subjects.id"), nullable=True)
    item: Mapped[SetupItem] = mapped_column(
        Enum(SetupItem, native_enum=False, length=32), nullable=False
    )
    acknowledged_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    acknowledged_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
