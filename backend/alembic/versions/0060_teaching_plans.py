"""teaching plans

Task 6.1. A tutor's plan for a class: `teaching_plans` (one per class per
status), `plan_slots` (the planned lesson occurrences) and `plan_breaks` (days
with no teaching). Three new tables, no existing one altered, so plain
`op.create_table` and no batch rebuild (`DB-17` does not apply).

A slot is a *planned* lesson and a `Lesson` the confirmed *actual* one; they are
never the same row (`E15`). Teaching and past-paper phases overlap by design
(AV-16), so no constraint orders the past-paper start against the slots.

`status` and `provenance` are VARCHAR (`native_enum=False`), so adding a member
needs no migration (`DB-5`). `plan_slots.sequence` is indexed but deliberately
not unique: a reflow renumbers many rows and a non-deferrable unique fails
mid-statement on Postgres while SQLite cannot express a deferrable one.

Nothing is backfilled: every table starts empty by construction.

Revision ID: 0060
Revises: 0059
Create Date: 2026-10-03

"""

import sqlalchemy as sa

from alembic import op

revision = "0060"
down_revision = "0059"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "teaching_plans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey(
                "organizations.id", name="fk_teaching_plans_organization_id_organizations"
            ),
            nullable=False,
        ),
        sa.Column(
            "group_id",
            sa.Integer(),
            sa.ForeignKey(
                "groups.id", name="fk_teaching_plans_group_id_groups", ondelete="CASCADE"
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum("draft", "accepted", name="teachingplanstatus", native_enum=False, length=16),
            nullable=False,
        ),
        sa.Column("exam_date", sa.Date(), nullable=False),
        sa.Column("lessons_per_week", sa.Integer(), nullable=False),
        sa.Column("lesson_minutes", sa.Integer(), nullable=False),
        sa.Column("past_paper_start_date", sa.Date(), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "accepted_by_id",
            sa.Integer(),
            sa.ForeignKey("users.id", name="fk_teaching_plans_accepted_by_id_users"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("group_id", "status", name="uq_teaching_plans_group_id_status"),
        sa.CheckConstraint(
            "lessons_per_week >= 1", name="ck_teaching_plans_lessons_per_week_positive"
        ),
        sa.CheckConstraint("lesson_minutes >= 1", name="ck_teaching_plans_lesson_minutes_positive"),
        sa.CheckConstraint(
            "past_paper_start_date IS NULL OR past_paper_start_date <= exam_date",
            name="ck_teaching_plans_past_papers_before_exam",
        ),
        sa.CheckConstraint(
            "status <> 'accepted' OR (accepted_at IS NOT NULL AND accepted_by_id IS NOT NULL)",
            name="ck_teaching_plans_accepted_has_acceptor",
        ),
    )
    op.create_index("ix_teaching_plans_organization_id", "teaching_plans", ["organization_id"])

    op.create_table(
        "plan_slots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "plan_id",
            sa.Integer(),
            sa.ForeignKey(
                "teaching_plans.id", name="fk_plan_slots_plan_id_teaching_plans", ondelete="CASCADE"
            ),
            nullable=False,
        ),
        sa.Column(
            "chapter_id",
            sa.Integer(),
            sa.ForeignKey(
                "chapters.id", name="fk_plan_slots_chapter_id_chapters", ondelete="RESTRICT"
            ),
            nullable=False,
        ),
        sa.Column("scheduled_date", sa.Date(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column(
            "provenance",
            sa.Enum(
                "generated",
                "manually_modified",
                "confirmed",
                "completed",
                name="planslotprovenance",
                native_enum=False,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_plan_slots_plan_id_sequence", "plan_slots", ["plan_id", "sequence"])
    op.create_index("ix_plan_slots_chapter_id", "plan_slots", ["chapter_id"])

    op.create_table(
        "plan_breaks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "plan_id",
            sa.Integer(),
            sa.ForeignKey(
                "teaching_plans.id",
                name="fk_plan_breaks_plan_id_teaching_plans",
                ondelete="CASCADE",
            ),
            nullable=False,
        ),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("label", sa.String(120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("end_date >= start_date", name="ck_plan_breaks_end_not_before_start"),
    )
    op.create_index("ix_plan_breaks_plan_id", "plan_breaks", ["plan_id"])


def downgrade() -> None:
    # Like 0058: warn rather than refuse. Nothing else references these tables,
    # so proceeding cannot corrupt anything — it can only discard a tutor's
    # plan, and the deploy log should say so plainly.
    bind = op.get_bind()
    for table in ("plan_breaks", "plan_slots", "teaching_plans"):
        count = bind.execute(sa.text(f"SELECT COUNT(*) FROM {table}")).scalar_one()  # noqa: S608 - fixed table names
        if count:
            print(  # noqa: T201 - alembic's own output channel is the deploy log
                f"WARNING: dropping {count} row(s) of {table}; not recoverable after this."
            )
    op.drop_index("ix_plan_breaks_plan_id", table_name="plan_breaks")
    op.drop_table("plan_breaks")
    op.drop_index("ix_plan_slots_chapter_id", table_name="plan_slots")
    op.drop_index("ix_plan_slots_plan_id_sequence", table_name="plan_slots")
    op.drop_table("plan_slots")
    op.drop_index("ix_teaching_plans_organization_id", table_name="teaching_plans")
    op.drop_table("teaching_plans")
