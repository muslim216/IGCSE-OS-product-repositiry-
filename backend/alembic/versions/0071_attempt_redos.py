"""attempt_redos: the record of an attempt a tutor let a student redo

A new table only; no existing row is read or changed. The old attempt is moved
here as a snapshot and its live rows are deleted by the application, never by
this migration (`PROD-7`, see the model docstring for why).

Revision ID: 0071
Revises: 0070
"""

import sqlalchemy as sa

from alembic import op

revision = "0071"
down_revision = "0070"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "attempt_redos",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey(
                "organizations.id", name="fk_attempt_redos_organization_id_organizations"
            ),
            nullable=False,
        ),
        sa.Column(
            "work_id",
            sa.Integer(),
            sa.ForeignKey("assessable_work.id", name="fk_attempt_redos_work_id_assessable_work"),
            nullable=False,
        ),
        sa.Column(
            "student_id",
            sa.Integer(),
            sa.ForeignKey("users.id", name="fk_attempt_redos_student_id_users"),
            nullable=False,
        ),
        sa.Column(
            "allowed_by_id",
            sa.Integer(),
            sa.ForeignKey("users.id", name="fk_attempt_redos_allowed_by_id_users"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        # Plain integer: the submission it names has been deleted.
        sa.Column("previous_submission_id", sa.Integer(), nullable=False),
        sa.Column("previous_final_marks", sa.Integer(), nullable=True),
        sa.Column("previous_max_marks", sa.Integer(), nullable=True),
        sa.Column("record", sa.JSON(), nullable=False),
    )
    op.create_index("ix_attempt_redos_organization_id", "attempt_redos", ["organization_id"])
    op.create_index("ix_attempt_redos_student_id", "attempt_redos", ["student_id"])


def downgrade() -> None:
    op.drop_index("ix_attempt_redos_student_id", table_name="attempt_redos")
    op.drop_index("ix_attempt_redos_organization_id", table_name="attempt_redos")
    op.drop_table("attempt_redos")
