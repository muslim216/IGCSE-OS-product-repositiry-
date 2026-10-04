"""lesson attendance, lesson mode, start times

Task 7.1 (AV-44, AV-109, AV-118). Lays all of Phase 7's schema so the tasks that
follow (surfaces, reminders, auto-taught) need no migration of their own.

`lessons.mode` backfills to `in_person` and `lessons.origin` to `tutor`: every
lesson that exists was recorded by a tutor. `start_time` is local wall-clock
time in the organization's timezone; NULL means unknown, never midnight
(`DB-9`). `plan_slots.start_time` / `cancelled_at` / `cancelled_by_id` are read
by task 7.4; NULL `cancelled_at` means not cancelled.

`lesson_attendance` is one row per (lesson, student). No row means attendance
was not taken, never absent (`PROD-2`). It is not a readiness factor (AV-33).

Existing tables are altered, so `batch_alter_table` with the naming convention
and explicitly named constraints (`DB-17`).

Revision ID: 0063
Revises: 0062
Create Date: 2026-10-04

"""

import sqlalchemy as sa

from alembic import op

NAMING = {
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
}

revision = "0063"
down_revision = "0062"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("lessons", naming_convention=NAMING) as batch:
        batch.add_column(
            sa.Column(
                "mode",
                sa.Enum("in_person", "online", name="lessonmode", native_enum=False, length=10),
                nullable=False,
                server_default="in_person",
            )
        )
        batch.add_column(sa.Column("start_time", sa.Time(), nullable=True))
        batch.add_column(
            sa.Column(
                "origin",
                sa.Enum("tutor", "plan", name="lessonorigin", native_enum=False, length=10),
                nullable=False,
                server_default="tutor",
            )
        )

    with op.batch_alter_table("plan_slots", naming_convention=NAMING) as batch:
        batch.add_column(sa.Column("start_time", sa.Time(), nullable=True))
        batch.add_column(sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("cancelled_by_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_plan_slots_cancelled_by_id_users", "users", ["cancelled_by_id"], ["id"]
        )

    op.create_table(
        "lesson_attendance",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey(
                "organizations.id", name="fk_lesson_attendance_organization_id_organizations"
            ),
            nullable=False,
        ),
        sa.Column(
            "lesson_id",
            sa.Integer(),
            sa.ForeignKey(
                "lessons.id", ondelete="CASCADE", name="fk_lesson_attendance_lesson_id_lessons"
            ),
            nullable=False,
        ),
        sa.Column(
            "student_id",
            sa.Integer(),
            sa.ForeignKey("users.id", name="fk_lesson_attendance_student_id_users"),
            nullable=False,
        ),
        sa.Column(
            "state",
            sa.Enum("present", "absent", name="attendancestate", native_enum=False, length=10),
            nullable=False,
        ),
        sa.Column(
            "source",
            sa.Enum(
                "tutor",
                "zoom",
                "google_meet",
                name="attendancesource",
                native_enum=False,
                length=12,
            ),
            nullable=False,
        ),
        sa.Column(
            "recorded_by_id",
            sa.Integer(),
            sa.ForeignKey("users.id", name="fk_lesson_attendance_recorded_by_id_users"),
            nullable=True,
        ),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "lesson_id", "student_id", name="uq_lesson_attendance_lesson_id_student_id"
        ),
    )
    op.create_index("ix_lesson_attendance_student_id", "lesson_attendance", ["student_id"])
    op.create_index(
        "ix_lesson_attendance_organization_id", "lesson_attendance", ["organization_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_lesson_attendance_organization_id", table_name="lesson_attendance")
    op.drop_index("ix_lesson_attendance_student_id", table_name="lesson_attendance")
    op.drop_table("lesson_attendance")

    with op.batch_alter_table("plan_slots", naming_convention=NAMING) as batch:
        batch.drop_constraint("fk_plan_slots_cancelled_by_id_users", type_="foreignkey")
        batch.drop_column("cancelled_by_id")
        batch.drop_column("cancelled_at")
        batch.drop_column("start_time")

    with op.batch_alter_table("lessons", naming_convention=NAMING) as batch:
        batch.drop_column("origin")
        batch.drop_column("start_time")
        batch.drop_column("mode")
