"""ai_usage_events: cache token counts, and tutor_id becomes nullable

Revision ID: 0079
Revises: 0078

Two metering gaps from the launch audit. C-3: prompt-cache reads and writes
were not counted, so spend was understated. C-14: a call with no tutor to
charge (a sweep, an organization with no tutor) was dropped instead of
recorded; tutor_id NULL now means system usage. Existing rows keep their
tutor_id, and the new cache columns are NULL for them (not counted then).
"""

import sqlalchemy as sa

from alembic import op

NAMING = {
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
}

revision = "0079"
down_revision = "0078"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("ai_usage_events", naming_convention=NAMING) as batch:
        batch.add_column(sa.Column("cache_write_tokens", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("cache_read_tokens", sa.Integer(), nullable=True))
        batch.alter_column("tutor_id", existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    # System rows have no tutor to put back; they would block NOT NULL.
    op.execute("DELETE FROM ai_usage_events WHERE tutor_id IS NULL")
    with op.batch_alter_table("ai_usage_events", naming_convention=NAMING) as batch:
        batch.alter_column("tutor_id", existing_type=sa.Integer(), nullable=False)
        batch.drop_column("cache_read_tokens")
        batch.drop_column("cache_write_tokens")
