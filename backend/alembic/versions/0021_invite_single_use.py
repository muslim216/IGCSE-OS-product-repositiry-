"""invites.used_at + an expiry backfill for codes issued without one

Invite codes were minted with expires_at NULL and no use limit, so any code
that ever leaked stayed a working, unauthenticated path into a tutor's
organization — and a parent-link code, which hands over one child's whole
academic record, could be redeemed by any number of accounts.

used_at records the redemption of a single-use code (parent_link). Group-join
codes stay multi-use by design — a tutor shares one link with a class — so an
expiry is what bounds those.

Existing rows are backfilled with a 14-day expiry from now rather than from
their creation date: expiring every outstanding code the moment this deploys
would strand parents and students mid-signup. It does mean a leaked old code
stays live for two more weeks; tutors who need one dead sooner can reissue,
which is a tutor-facing action rather than a migration concern.

Revision ID: 0021
Revises: 0020
Create Date: 2026-07-25

"""
from datetime import datetime, timedelta, timezone

import sqlalchemy as sa

from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("invites") as batch:
        batch.add_column(sa.Column("used_at", sa.DateTime(timezone=True), nullable=True))

    # The deadline is computed here and sent as a bound parameter rather than
    # built from the database's own now(): Postgres and SQLite spell date
    # arithmetic differently, and "14 days from when this migration ran" is what
    # is wanted regardless.
    invites = sa.table("invites", sa.column("expires_at", sa.DateTime(timezone=True)))
    op.execute(
        invites.update()
        .where(invites.c.expires_at.is_(None))
        .values(expires_at=datetime.now(timezone.utc) + timedelta(days=14))
    )


def downgrade() -> None:
    with op.batch_alter_table("invites") as batch:
        batch.drop_column("used_at")
