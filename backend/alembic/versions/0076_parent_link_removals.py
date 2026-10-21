"""parent_link_removals: the record of who ended a parent's access to a child

A new table only; no existing row is read or changed.

Revision ID: 0076
Revises: 0075
"""

import sqlalchemy as sa

from alembic import op

revision = "0076"
down_revision = "0075"
branch_labels = None
depends_on = None


def _fk(col: str, table: str) -> sa.ForeignKey:
    return sa.ForeignKey(f"{table}.id", name=f"fk_parent_link_removals_{col}_{table}")


def upgrade() -> None:
    op.create_table(
        "parent_link_removals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organization_id", sa.Integer(), _fk("organization_id", "organizations"), nullable=False
        ),
        # Plain integer: the link it names has been deleted.
        sa.Column("link_id", sa.Integer(), nullable=False),
        sa.Column("parent_id", sa.Integer(), _fk("parent_id", "users"), nullable=False),
        sa.Column("student_id", sa.Integer(), _fk("student_id", "users"), nullable=False),
        sa.Column("removed_by_id", sa.Integer(), _fk("removed_by_id", "users"), nullable=False),
        sa.Column("removed_by_role", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_parent_link_removals_student_id", "parent_link_removals", ["student_id"])


def downgrade() -> None:
    op.drop_index("ix_parent_link_removals_student_id", table_name="parent_link_removals")
    op.drop_table("parent_link_removals")
