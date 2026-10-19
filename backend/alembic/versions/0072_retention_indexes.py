"""retention indexes: the two lookups the daily retention sweep makes

Two indexes only; no row is read or changed. `factor_evaluations` is the
largest table, and the sweep's "older than 90 days" walk would otherwise scan
it every night; `jobs` gets the same for "finished, older than 30 days"
(`services/retention.py`). Built while the tables are small, before launch.

Revision ID: 0072
Revises: 0071
"""

from alembic import op

revision = "0072"
down_revision = "0071"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_factor_evaluations_created_at_id", "factor_evaluations", ["created_at", "id"]
    )
    op.create_index("ix_jobs_status_created_at", "jobs", ["status", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_jobs_status_created_at", table_name="jobs")
    op.drop_index("ix_factor_evaluations_created_at_id", table_name="factor_evaluations")
