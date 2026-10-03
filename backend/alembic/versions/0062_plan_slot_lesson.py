"""plan slot lesson link

Task 6.5 (AV-17, E15). `plan_slots.lesson_id`: the lesson that confirmed a
slot. NULL means the slot has not been taught (`DB-9`), so "the next unstarted
slot" is `lesson_id IS NULL`.

UNIQUE, so one lesson confirms at most one slot and a double-submit cannot link
twice. ON DELETE SET NULL: deleting a lesson frees its slot rather than taking
the plan's intention with it. The UNIQUE constraint carries the index the
foreign key would otherwise need (`DB-11`), so none is added beside it.

An existing table is altered, so `batch_alter_table` with the naming
convention and explicitly named constraints (`DB-17`). No backfill: no slot
has been confirmed by a lesson before this.

Revision ID: 0062
Revises: 0061
Create Date: 2026-10-03

"""

import sqlalchemy as sa

from alembic import op

NAMING = {
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
}

revision = "0062"
down_revision = "0061"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("plan_slots", naming_convention=NAMING) as batch:
        batch.add_column(sa.Column("lesson_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_plan_slots_lesson_id_lessons",
            "lessons",
            ["lesson_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_unique_constraint("uq_plan_slots_lesson_id", ["lesson_id"])


def downgrade() -> None:
    with op.batch_alter_table("plan_slots", naming_convention=NAMING) as batch:
        batch.drop_constraint("uq_plan_slots_lesson_id", type_="unique")
        batch.drop_constraint("fk_plan_slots_lesson_id_lessons", type_="foreignkey")
        batch.drop_column("lesson_id")
