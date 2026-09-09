"""Which rules a marking-rules summary was built from

Task 3.2c, fixing a race 3.2c shipped with. Its docstring claimed staleness was
impossible by construction — clear the summary on write, rebuild in a job — and
that was wrong, because the job reads the rules, then awaits a model call, then
writes:

    1. tutor saves rules A; summary cleared; job A queued
    2. job A reads A and starts the model call
    3. tutor saves rules B; summary cleared (already null); job B queued
    4. job A commits summary-of-A — the summary is now stale
    5. job B sees a non-null summary and returns early, forever

This column is the compare-and-swap that closes it: the SHA-256 of the rules a
summary was built from. The job writes only if the subject's rules still hash to
what it summarised, and skips only if the hash already matches — so a duplicate
delivery is free and a superseded one is discarded. A hash rather than the text
again because it is a fixed 64 bytes against a field capped at 8,000.

It is also set when a summarisation legitimately produces nothing, so that case
is remembered rather than paid for on every redelivery.

`batch_alter_table` with 0020's naming convention, per `DB-17`.

Revision ID: 0037
Revises: 0036
Create Date: 2026-09-09

"""

import sqlalchemy as sa

from alembic import op

NAMING = {
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
}

revision = "0037"
down_revision = "0036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("subjects", naming_convention=NAMING) as batch:
        batch.add_column(sa.Column("marking_rules_summary_of", sa.String(64), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("subjects", naming_convention=NAMING) as batch:
        batch.drop_column("marking_rules_summary_of")
