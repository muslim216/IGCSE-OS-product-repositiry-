"""teaching plans: papers with their own dates, and a revision start date

T-076. A plan has 1-6 exam papers, each with its own date, and an optional date
revision starts; chapters are scheduled only before it. Additive only, so a
failed deploy cannot strand the previous code (no column is dropped or retyped):
a new `teaching_plan_papers` table and a nullable `teaching_plans.revision_start_date`.

`teaching_plans.exam_date` stays and is kept equal to the earliest paper's date
by the service, so everything that reads it today keeps working.

Backfill: every existing plan gets one paper named "Exam" from its exam date.
`revision_start_date` stays NULL (teaching runs to the exam, as before).

Revision ID: 0080
Revises: 0079
Create Date: 2026-11-16

"""

import sqlalchemy as sa

from alembic import op

# SQLite rebuilds a table to alter it, so every constraint must be nameable
# (`DB-17`); the convention is the one from 0020_past_papers.py.
NAMING = {
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
}

revision = "0080"
down_revision = "0079"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("teaching_plans", naming_convention=NAMING) as batch:
        batch.add_column(sa.Column("revision_start_date", sa.Date(), nullable=True))

    op.create_table(
        "teaching_plan_papers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "plan_id",
            sa.Integer(),
            sa.ForeignKey(
                "teaching_plans.id", ondelete="CASCADE", name="fk_teaching_plan_papers_plan_id"
            ),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("exam_date", sa.Date(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("plan_id", "position", name="uq_teaching_plan_papers_plan_id_position"),
    )
    op.create_index("ix_teaching_plan_papers_plan_id", "teaching_plan_papers", ["plan_id"])

    # One statement, not a loop: every plan keeps its exam date as paper 1.
    op.execute(
        "INSERT INTO teaching_plan_papers "
        "(plan_id, name, exam_date, position, created_at) "
        "SELECT id, 'Exam', exam_date, 1, CURRENT_TIMESTAMP "
        "FROM teaching_plans"
    )


def downgrade() -> None:
    op.drop_index("ix_teaching_plan_papers_plan_id", table_name="teaching_plan_papers")
    op.drop_table("teaching_plan_papers")
    with op.batch_alter_table("teaching_plans", naming_convention=NAMING) as batch:
        batch.drop_column("revision_start_date")
