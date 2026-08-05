"""ai_usage_events provider/prompt_version/cost_usd + jobs.run_after

Multi-provider AI routing (services/ai.py) means a usage row must say which
vendor and which prompt version produced it, and cost analytics needs an
estimated spend per call. jobs.run_after lets the worker hold a job until a
future time, which is what readiness-synthesis coalescing is built on.

Revision ID: 0018
Revises: 0017
Create Date: 2026-07-24

"""
import sqlalchemy as sa

from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("ai_usage_events") as batch:
        batch.add_column(
            sa.Column(
                "provider",
                sa.String(length=16),
                nullable=False,
                server_default="anthropic",
            )
        )
        batch.add_column(sa.Column("prompt_version", sa.String(length=16), nullable=True))
        batch.add_column(sa.Column("cost_usd", sa.Float(), nullable=True))

    # An AI-drafted mark records which model and prompt version produced it.
    with op.batch_alter_table("question_marks") as batch:
        batch.add_column(sa.Column("ai_model", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("ai_prompt_version", sa.String(length=16), nullable=True))

    with op.batch_alter_table("jobs") as batch:
        batch.add_column(sa.Column("run_after", sa.DateTime(timezone=True), nullable=True))
    # The worker filters pending jobs by run_after on every poll.
    op.create_index("ix_jobs_status_run_after", "jobs", ["status", "run_after"])


def downgrade() -> None:
    op.drop_index("ix_jobs_status_run_after", table_name="jobs")
    with op.batch_alter_table("jobs") as batch:
        batch.drop_column("run_after")

    with op.batch_alter_table("question_marks") as batch:
        batch.drop_column("ai_prompt_version")
        batch.drop_column("ai_model")

    with op.batch_alter_table("ai_usage_events") as batch:
        batch.drop_column("cost_usd")
        batch.drop_column("prompt_version")
        batch.drop_column("provider")
