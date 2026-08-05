"""lessons core entity (schedule_slots rename + lessons/lesson_topics/lesson_observations)

Revision ID: 0014
Revises: 0013
Create Date: 2026-07-23

"""

import sqlalchemy as sa

from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The old "lessons" table was a recurring weekday/time template, not a
    # taught lesson event — rename it out of the way so "lessons" can become
    # the new core entity.
    op.rename_table("lessons", "schedule_slots")

    op.create_table(
        "lessons",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False
        ),
        sa.Column("group_id", sa.Integer(), sa.ForeignKey("groups.id"), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("duration_min", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "schedule_slot_id", sa.Integer(), sa.ForeignKey("schedule_slots.id"), nullable=True
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "lesson_topics",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("lesson_id", sa.Integer(), sa.ForeignKey("lessons.id"), nullable=False),
        sa.Column("topic_id", sa.Integer(), sa.ForeignKey("topics.id"), nullable=False),
        sa.UniqueConstraint("lesson_id", "topic_id"),
    )
    op.create_table(
        "lesson_observations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("lesson_id", sa.Integer(), sa.ForeignKey("lessons.id"), nullable=False),
        sa.Column("student_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("topic_id", sa.Integer(), sa.ForeignKey("topics.id"), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    with op.batch_alter_table("assignments") as batch_op:
        batch_op.add_column(sa.Column("lesson_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key("fk_assignments_lesson_id", "lessons", ["lesson_id"], ["id"])


def downgrade() -> None:
    with op.batch_alter_table("assignments") as batch_op:
        batch_op.drop_constraint("fk_assignments_lesson_id", type_="foreignkey")
        batch_op.drop_column("lesson_id")
    op.drop_table("lesson_observations")
    op.drop_table("lesson_topics")
    op.drop_table("lessons")
    op.rename_table("schedule_slots", "lessons")
