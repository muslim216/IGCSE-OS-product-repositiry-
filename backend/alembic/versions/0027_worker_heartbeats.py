"""worker liveness moves into the database

Task 1.3 (AV-82, E19) splits the job worker out of the API's lifespan so the
two can scale independently. The four liveness clocks the readiness endpoint
reads — started_at, last_loop_at, job_started_at and the restart history —
lived in module globals in `workers/jobs.py`, which was correct only while the
worker and the API were the same process. Once they are not, the API cannot
see the worker's memory, and `/health/ready` would answer about a worker that
is not the one doing the work.

One row per worker process, keyed by a per-process id, so N workers are N rows
and a worker that vanished is a row that stopped updating rather than one that
silently changed meaning.

Creates a new table only — no existing table is altered, so `DB-17`'s
batch_alter_table dance does not apply here.

Revision ID: 0027
Revises: 0026
Create Date: 2026-08-28

"""

import sqlalchemy as sa

from alembic import op

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "worker_heartbeats",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("worker_id", sa.String(length=64), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_loop_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("job_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("restarts", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        # Named explicitly rather than left to the default: the readiness
        # endpoint upserts on this column, and an unnamed constraint is one
        # SQLite cannot reflect if a later migration ever rebuilds the table
        # (DB-17).
        sa.UniqueConstraint("worker_id", name="uq_worker_heartbeats_worker_id"),
    )


def downgrade() -> None:
    op.drop_table("worker_heartbeats")
