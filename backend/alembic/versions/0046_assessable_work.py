"""Assessable work: one parent row per homework/past-paper/mock instance

Three child tables (`assignments`, `past_papers`, `mocks`) each carry their
own `organization_id`, and five cross-kind queries OR those three columns
together to answer "does this org have any work of any kind here" — a missed
arm in one of the three fails silently rather than loudly. `assessable_work`
gives those queries one column to filter on instead, copied from the child at
creation time (for an assignment, from its Group, which is where an
assignment's org and subject actually live).

This migration only creates the table and adds a nullable, unique `work_id`
pointer to each child. Nothing reads it yet, and no existing row is backfilled
— that is a separate migration once the backfill script exists, so this one
stays reversible with nothing but empty columns to drop.

Revision ID: 0046
Revises: 0045
Create Date: 2026-09-15

"""

import sqlalchemy as sa

from alembic import op

# SQLite rebuilds a whole table to add a foreign key, which means every
# constraint on it has to be nameable.
NAMING = {
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
}

revision = "0046"
down_revision = "0045"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "assessable_work",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("subject_id", sa.Integer(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "homework", "past_paper", "mock", name="workkind", native_enum=False, length=16
            ),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_assessable_work_organization_id_organizations",
        ),
        sa.ForeignKeyConstraint(
            ["subject_id"], ["subjects.id"], name="fk_assessable_work_subject_id_subjects"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_assessable_work_organization_id_subject_id",
        "assessable_work",
        ["organization_id", "subject_id"],
    )

    with op.batch_alter_table("assignments", naming_convention=NAMING) as batch:
        batch.add_column(
            sa.Column(
                "work_id",
                sa.Integer(),
                sa.ForeignKey("assessable_work.id", name="fk_assignments_work_id_assessable_work"),
                nullable=True,
            )
        )
        batch.create_unique_constraint("uq_assignments_work_id", ["work_id"])

    with op.batch_alter_table("past_papers", naming_convention=NAMING) as batch:
        batch.add_column(
            sa.Column(
                "work_id",
                sa.Integer(),
                sa.ForeignKey("assessable_work.id", name="fk_past_papers_work_id_assessable_work"),
                nullable=True,
            )
        )
        batch.create_unique_constraint("uq_past_papers_work_id", ["work_id"])

    with op.batch_alter_table("mocks", naming_convention=NAMING) as batch:
        batch.add_column(
            sa.Column(
                "work_id",
                sa.Integer(),
                sa.ForeignKey("assessable_work.id", name="fk_mocks_work_id_assessable_work"),
                nullable=True,
            )
        )
        batch.create_unique_constraint("uq_mocks_work_id", ["work_id"])


def downgrade() -> None:
    with op.batch_alter_table("mocks", naming_convention=NAMING) as batch:
        batch.drop_constraint("uq_mocks_work_id", type_="unique")
        batch.drop_column("work_id")

    with op.batch_alter_table("past_papers", naming_convention=NAMING) as batch:
        batch.drop_constraint("uq_past_papers_work_id", type_="unique")
        batch.drop_column("work_id")

    with op.batch_alter_table("assignments", naming_convention=NAMING) as batch:
        batch.drop_constraint("uq_assignments_work_id", type_="unique")
        batch.drop_column("work_id")

    op.drop_index("ix_assessable_work_organization_id_subject_id", table_name="assessable_work")
    op.drop_table("assessable_work")
