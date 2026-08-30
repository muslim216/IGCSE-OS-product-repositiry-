"""jobs record which worker claimed them, so an orphan can be recovered

Task 1.5 (AV-84) closes the queue's one unrecoverable state. A worker killed
mid-job left its row in `running` forever: no retry path looks at `running`, so
the work simply stopped, and the only trace was a number on /health/ready that
nothing watched. `test_a_job_left_running_by_a_killed_worker_is_visible` recorded
that as a known gap rather than asserting a recovery that did not exist.

`claimed_by` is stamped on claim and cleared on every terminal outcome, so a
non-NULL pair on a `running` row names the process that owes an answer for it.
The sweep in `workers/jobs.py` requeues a row whose claimant no longer has a
heartbeat row — a worker that is gone, not one that is slow.

Deliberately **not** a foreign key to `worker_heartbeats.worker_id`, even though
that is where the value comes from: heartbeat rows are reaped, and a claim whose
worker row has vanished is the sweep's entire signal. A FK would either forbid
that reap or cascade away the evidence the sweep reads.

The index matches the sweep's filter and is declared in the model too (`DB-12`).

`batch_alter_table` with the naming convention from 0020, per `DB-17`: SQLite
rebuilds a table on ALTER and refuses unnamed reflected constraints.

Revision ID: 0028
Revises: 0027
Create Date: 2026-08-29

"""

import sqlalchemy as sa

from alembic import op

NAMING = {
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
}

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("jobs", naming_convention=NAMING) as batch:
        # Nullable, with no backfill: rows already `running` when this lands
        # have no claimant to name, and inventing one would make the sweep
        # attribute them to a worker that never held them. They stay exactly as
        # stuck as they are today — visible in the queue counts — rather than
        # being silently requeued by a migration.
        batch.add_column(sa.Column("claimed_by", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True))

    op.create_index("ix_jobs_status_claimed_at", "jobs", ["status", "claimed_at"])


def downgrade() -> None:
    op.drop_index("ix_jobs_status_claimed_at", table_name="jobs")
    with op.batch_alter_table("jobs", naming_convention=NAMING) as batch:
        batch.drop_column("claimed_at")
        batch.drop_column("claimed_by")
