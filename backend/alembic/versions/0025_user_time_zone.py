"""users.time_zone — a student or parent may not share the tutor's zone

The organization's timezone (0022) answers "what day is it" for the account:
today's lessons, the weekly narrative, anything that names a day. But the
people seeing those answers may live somewhere else — a tutor in Cairo with
students in Dubai and parents in London has three honest "todays", and one
column cannot hold them.

This column is the per-user override (AV-67). It is nullable, and None does
NOT mean UTC the way an unset organization zone does — it means "use the
organization's zone". The org setting remains the single default; a stored
per-user value is always a deliberate act by that user, validated against
the same tz database at the edge (services/timezones.py) because it arrives
from a browser and is untrusted input.

Surfaces are converted to read this column one at a time as their design
lands (Phase D); nothing reads it yet except /me, which is what makes the
override settable at all. The weekly send deliberately ignores it (AV-90):
one send moment per account, on the tutor's clock.

Revision ID: 0025
Revises: 0023
Create Date: 2026-08-22

"""

import sqlalchemy as sa

from alembic import op

# Same convention as 0020/0022. A bare nullable column, no constraints added,
# so SQLite's rebuild behaviour is not exercised — the convention is passed
# regardless because DB-17 as written admits no exception.
NAMING = {
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
}

revision = "0025"
# If 0024_drop_chat (task 0.3's branch) merges before this one, rebase this
# migration onto it: down_revision becomes "0024". Two heads are an alembic
# error, and branch-per-task makes this collision ordinary — rebase, do not
# renumber.
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users", naming_convention=NAMING) as batch:
        batch.add_column(sa.Column("time_zone", sa.String(length=64), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("users", naming_convention=NAMING) as batch:
        batch.drop_column("time_zone")
