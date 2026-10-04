"""The teaching plan: what a tutor intends to teach a class, and when.

A plan belongs to a class (`Group`, AV-13). A class has one subject (AV-72), so
its chapters come from `group.subject` and a plan needs no subject column.

A `PlanSlot` is a *planned* lesson; a `Lesson` is the confirmed *actual* one.
They are never the same row (`E15`): a slot that gets taught keeps its own row
and records that in `provenance`, so the plan stays a record of the intention
even after reality diverges.

Teaching and past-paper phases overlap by design (AV-16), so nothing here or in
a reader may assume the past-paper start falls after the last chapter slot.

Two things the schema does not enforce, so every writer must: a plan's
`organization_id` is its class's, and a slot's chapter belongs to the class's
subject.

Nothing reads a draft plan (task 6.4): any reader must filter
`status == accepted`. The plan and its exam date are tutor-only (AV-19).
"""

import enum
from datetime import date, datetime, time

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Time,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class TeachingPlanStatus(str, enum.Enum):
    draft = "draft"
    accepted = "accepted"


class PlanSlotProvenance(str, enum.Enum):
    generated = "generated"
    manually_modified = "manually_modified"
    confirmed = "confirmed"
    completed = "completed"


class TeachingPlan(TimestampMixin, Base):
    """One class's plan. Starts `draft`; only the tutor accepting it makes it live."""

    __tablename__ = "teaching_plans"
    # Declared here as well as in migration 0060 (`DB-12`).
    __table_args__ = (
        # At most one draft and one accepted plan per class. Not one plan per
        # class: a re-plan (task 6.6) is drafted and waits for acceptance while
        # the accepted plan stays live. Two drafts would be ambiguous.
        UniqueConstraint("group_id", "status", name="uq_teaching_plans_group_id_status"),
        CheckConstraint(
            "lessons_per_week >= 1", name="ck_teaching_plans_lessons_per_week_positive"
        ),
        CheckConstraint("lesson_minutes >= 1", name="ck_teaching_plans_lesson_minutes_positive"),
        CheckConstraint(
            "past_paper_start_date IS NULL OR past_paper_start_date <= exam_date",
            name="ck_teaching_plans_past_papers_before_exam",
        ),
        # An implication on `accepted` only, so adding a status member later
        # (`DB-5`) does not mean rewriting this constraint.
        CheckConstraint(
            "status <> 'accepted' OR (accepted_at IS NOT NULL AND accepted_by_id IS NOT NULL)",
            name="ck_teaching_plans_accepted_has_acceptor",
        ),
        Index("ix_teaching_plans_organization_id", "organization_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    # Deleting a class removes its plans through the database's ON DELETE
    # CASCADE: `api/groups.py:delete_group` does a bare `db.delete(group)` and
    # `Group` carries no relationship to plans. That holds only where foreign
    # keys are enforced — Postgres, which is production and local dev. The
    # SQLite test suite runs with them off, so there a deleted class leaves
    # its plans behind and no test may rely on the cascade.
    group_id: Mapped[int] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[TeachingPlanStatus] = mapped_column(
        Enum(TeachingPlanStatus, native_enum=False, length=16),
        default=TeachingPlanStatus.draft,
        nullable=False,
    )
    exam_date: Mapped[date] = mapped_column(Date, nullable=False)
    lessons_per_week: Mapped[int] = mapped_column(Integer, nullable=False)
    lesson_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    # NULL means the tutor has not said when past papers start, so the
    # past-paper phase has not started. Never read NULL as "started" (`DB-9`).
    past_paper_start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    accepted_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    # What the last drafting run did and why (task 6.3, PROD-1, PROD-2). NULL
    # means the plan has never been drafted. Generic JSON, never JSONB (DB-7).
    # Written on every outcome, so a tutor can tell an AI-weighted plan from an
    # even split. Shape:
    #   {"status": "drafted" | "failed" | "skipped",
    #    "drafted_at": ISO-8601 UTC, "prompt_version": str | None,
    #    "weight_source": "ai" | "stored_chapter_weights" | "ai_unusable" | None,
    #    "degraded_reason": str | None, "guidance_used": bool,
    #    "guidance_note": str | None,
    #    "defaulted_chapters": int, "clamped_chapters": int,
    #    "chapters": [{"chapter_id", "weight", "reason"}],  # reason cut to ~300 chars
    #    "failure": {"code": "not_enough_lessons" | "no_chapters",
    #                "message": str, "lessons": int | None,
    #                "chapters": int | None} | None}
    draft_result: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    slots: Mapped[list["PlanSlot"]] = relationship(
        back_populates="plan",
        order_by="PlanSlot.sequence",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    breaks: Mapped[list["PlanBreak"]] = relationship(
        back_populates="plan", cascade="all, delete-orphan", passive_deletes=True
    )


class PlanSlot(TimestampMixin, Base):
    """One planned lesson occurrence. Tenancy is scoped through its plan (`DB-2`)."""

    __tablename__ = "plan_slots"
    # Declared here as well as in migration 0060 (`DB-12`).
    __table_args__ = (
        # Deliberately not unique. A reorder or reflow renumbers many rows, and
        # a non-deferrable unique constraint fails mid-statement on Postgres
        # while SQLite has no deferrable unique at all: a constraint that
        # behaves differently on the two is the `RISK-3` shape.
        Index("ix_plan_slots_plan_id_sequence", "plan_id", "sequence"),
        # Task 6.8 reads "the slots for this chapter" (`DB-11`).
        Index("ix_plan_slots_chapter_id", "chapter_id"),
        # One lesson confirms at most one slot. The unique constraint is also
        # the FK's index (`DB-11`). Declared here as well as in 0062 (`DB-12`).
        UniqueConstraint("lesson_id", name="uq_plan_slots_lesson_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(
        ForeignKey("teaching_plans.id", ondelete="CASCADE"), nullable=False
    )
    # RESTRICT: removing a chapter is task 6.8's job, because it reflows the
    # plan. Until that exists the database refuses rather than silently
    # destroying a slot the tutor may have hand-edited (AV-77).
    chapter_id: Mapped[int] = mapped_column(
        ForeignKey("chapters.id", ondelete="RESTRICT"), nullable=False
    )
    scheduled_date: Mapped[date] = mapped_column(Date, nullable=False)
    # Order within the plan; two lessons can share a date.
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    provenance: Mapped[PlanSlotProvenance] = mapped_column(
        Enum(PlanSlotProvenance, native_enum=False, length=20),
        default=PlanSlotProvenance.generated,
        nullable=False,
    )

    # The lesson that confirmed this slot (task 6.5, E15). NULL means the slot
    # has not been taught: never read NULL as "taught" (`DB-9`). SET NULL so
    # deleting a lesson frees the slot; SQLite (tests) has FKs off, so
    # `services/plan_lessons.py` unlinks explicitly as well.
    lesson_id: Mapped[int | None] = mapped_column(
        ForeignKey("lessons.id", ondelete="SET NULL", name="fk_plan_slots_lesson_id_lessons"),
        nullable=True,
    )

    # This lesson's own start time, defaulted from the weekly timetable and
    # editable per lesson. NULL means unknown — never read it as midnight (`DB-9`).
    start_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    # NULL means not cancelled (`DB-9`).
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", name="fk_plan_slots_cancelled_by_id_users"), nullable=True
    )

    plan: Mapped[TeachingPlan] = relationship(back_populates="slots")


class PlanBreak(TimestampMixin, Base):
    """A stretch of days with no teaching (holiday, mock week). Inclusive of both ends."""

    __tablename__ = "plan_breaks"
    # Declared here as well as in migration 0060 (`DB-12`).
    __table_args__ = (
        CheckConstraint("end_date >= start_date", name="ck_plan_breaks_end_not_before_start"),
        Index("ix_plan_breaks_plan_id", "plan_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(
        ForeignKey("teaching_plans.id", ondelete="CASCADE"), nullable=False
    )
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    # A one-day break has start == end.
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    label: Mapped[str] = mapped_column(String(120), nullable=False)

    plan: Mapped[TeachingPlan] = relationship(back_populates="breaks")
