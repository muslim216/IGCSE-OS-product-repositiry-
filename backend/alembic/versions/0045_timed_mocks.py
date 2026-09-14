"""Timed mocks: the clock is the server's, and late is flagged not blocked

`mock_openings` records when each student first opened each mock — the moment
its clock started. It is a table rather than a column on `submissions` because
the clock has to start before a submission exists, and because a student who
opens a paper and never hands it in is a real state worth holding.

`submissions.measured_minutes` is how long they actually took, measured from
that row; `submissions.submitted_late` is whether it arrived after time was up.
Both are null/false for everything that came before, which is honest: nothing
measured those sittings, and `PROD-2` forbids inventing a figure to fill the
gap.

Revision ID: 0045
Revises: 0044
Create Date: 2026-09-14

"""

import sqlalchemy as sa

from alembic import op

NAMING = {
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
}

revision = "0045"
down_revision = "0044"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mock_openings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("mock_id", sa.Integer(), nullable=False),
        sa.Column("student_id", sa.Integer(), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["mock_id"], ["mocks.id"], name="fk_mock_openings_mock_id_mocks"),
        sa.ForeignKeyConstraint(
            ["student_id"], ["users.id"], name="fk_mock_openings_student_id_users"
        ),
        sa.PrimaryKeyConstraint("id"),
        # The clock starts once. A second open — a reload, a double-click, a
        # second device — collides here rather than restarting it.
        sa.UniqueConstraint("mock_id", "student_id", name="uq_mock_openings_mock_id_student_id"),
    )
    with op.batch_alter_table("submissions", naming_convention=NAMING) as batch:
        batch.add_column(sa.Column("measured_minutes", sa.Integer(), nullable=True))
        # Server default as well as a Python default: the column is NOT NULL and
        # existing rows need a value, and `server_default` is what supplies it
        # without a separate UPDATE.
        batch.add_column(
            sa.Column("submitted_late", sa.Boolean(), nullable=False, server_default=sa.false())
        )


def downgrade() -> None:
    with op.batch_alter_table("submissions", naming_convention=NAMING) as batch:
        batch.drop_column("submitted_late")
        batch.drop_column("measured_minutes")
    op.drop_table("mock_openings")
