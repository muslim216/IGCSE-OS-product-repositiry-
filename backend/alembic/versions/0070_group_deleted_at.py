"""groups.deleted_at / deleted_by_id: deleting a class hides it, it does not erase it

Revision ID: 0070
Revises: 0069
"""

import sqlalchemy as sa

from alembic import op

# Naming convention from 0020_past_papers.py: SQLite rebuilds the table on ALTER and
# refuses unnamed reflected constraints.
NAMING = {
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
}

revision = "0070"
down_revision = "0069"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # No index: every read of `groups` is already narrowed by organization or tutor,
    # and a tutor has a handful of classes, so `deleted_at IS NULL` filters a tiny set.
    with op.batch_alter_table("groups", naming_convention=NAMING) as batch:
        batch.add_column(sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("deleted_by_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_groups_deleted_by_id_users", "users", ["deleted_by_id"], ["id"]
        )


def downgrade() -> None:
    with op.batch_alter_table("groups", naming_convention=NAMING) as batch:
        batch.drop_constraint("fk_groups_deleted_by_id_users", type_="foreignkey")
        batch.drop_column("deleted_by_id")
        batch.drop_column("deleted_at")
