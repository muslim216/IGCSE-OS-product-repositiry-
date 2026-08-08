"""organizations.timezone — so "today" means today where the tutor is

Every "today" in the product was computed as datetime.now(timezone.utc), and
no timezone was stored anywhere: not on Organization, not on User, and
ScheduleSlot carries a bare weekday and start_time with no zone at all. A
tutor in Cairo (UTC+3) opening the app at 01:00 local therefore saw
yesterday's lessons, because in UTC it was still 22:00 the day before.

That is survivable on a dashboard where lessons are one panel of four. It is
not survivable on a surface whose headline sentence is "Two lessons today",
which is what the experience redesign makes it.

The column is nullable, and unset means UTC: backfilling a guess would be
worse than the honest fallback, since a wrong stored zone is invisible while
an absent one can be asked about. It holds an IANA name and is validated
against zoneinfo.available_timezones() before it is ever written — the value
arrives from the browser, so it is untrusted input.

Revision ID: 0022
Revises: 0021
Create Date: 2026-08-08

"""

import sqlalchemy as sa

from alembic import op

# Same convention as 0020_past_papers.py. This migration adds no constraint —
# a bare nullable column to a table with no foreign keys — so nothing here can
# hit SQLite's refusal to rebuild a table around an unnamed reflected
# constraint, which is the failure DB-17 exists to prevent. It is passed
# regardless because DB-17 as written admits no exception. See the PR notes:
# the current head, 0021_invite_single_use.py, adds a column with a bare
# batch_alter_table and no convention, so either that migration breaks DB-17 or
# DB-17's scope is narrower than its text. Recorded as a Known Gap (GOV-3),
# with a proposal to narrow DB-17 to migrations that add a constraint.
NAMING = {
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
}

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("organizations", naming_convention=NAMING) as batch:
        batch.add_column(sa.Column("timezone", sa.String(length=64), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("organizations", naming_convention=NAMING) as batch:
        batch.drop_column("timezone")
