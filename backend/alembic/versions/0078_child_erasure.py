"""child erasure: request + export tables, users flags, audit rows that outlive a child

Schema only (audit P-3, part 1 of 3). The two audit tables lose NOT NULL on the
key that pointed at the child's data, so erasing it can leave the tutor's
decision on record. Numbered 0078 because 0077 is taken by the open parent-link
PR (#193).

Revision ID: 0078
Revises: 0077
"""

import sqlalchemy as sa

from alembic import op

NAMING = {
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
}

revision = "0078"
down_revision = "0077"
branch_labels = None
depends_on = None


def _fk(table: str, col: str, target: str, **kw) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint([col], [f"{target}.id"], name=f"fk_{table}_{col}_{target}", **kw)


def upgrade() -> None:
    with op.batch_alter_table("users", naming_convention=NAMING) as batch:
        batch.add_column(sa.Column("erasure_requested_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("deleted_at", sa.DateTime(timezone=True)))
    with op.batch_alter_table("mark_override_audit", naming_convention=NAMING) as batch:
        batch.alter_column("question_mark_id", existing_type=sa.Integer(), nullable=True)
    with op.batch_alter_table("custom_criterion_score_audit", naming_convention=NAMING) as batch:
        batch.alter_column("student_id", existing_type=sa.Integer(), nullable=True)

    op.create_table(
        "erasure_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("student_id", sa.Integer(), nullable=False),
        sa.Column("requested_by_id", sa.Integer(), nullable=True),
        sa.Column("requested_role", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("pending_paths", sa.JSON()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        _fk("erasure_requests", "organization_id", "organizations"),
        _fk("erasure_requests", "student_id", "users"),
        _fk("erasure_requests", "requested_by_id", "users", ondelete="SET NULL"),
    )
    op.create_index(
        "uq_erasure_requests_pending_student",
        "erasure_requests",
        ["student_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
        sqlite_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "ix_erasure_requests_status_scheduled_for",
        "erasure_requests",
        ["status", "scheduled_for"],
    )

    op.create_table(
        "data_exports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("student_id", sa.Integer(), nullable=False),
        sa.Column("requested_by_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("storage_key", sa.String(length=255)),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        _fk("data_exports", "organization_id", "organizations"),
        _fk("data_exports", "student_id", "users"),
        _fk("data_exports", "requested_by_id", "users", ondelete="SET NULL"),
    )
    op.create_index("ix_data_exports_status_expires_at", "data_exports", ["status", "expires_at"])


def downgrade() -> None:
    op.drop_index("ix_data_exports_status_expires_at", table_name="data_exports")
    op.drop_table("data_exports")
    op.drop_index("ix_erasure_requests_status_scheduled_for", table_name="erasure_requests")
    op.drop_index("uq_erasure_requests_pending_student", table_name="erasure_requests")
    op.drop_table("erasure_requests")

    # Rows the erasure nulled have nothing to point at, so they cannot satisfy
    # NOT NULL; the restored schema cannot hold them.
    op.execute("DELETE FROM custom_criterion_score_audit WHERE student_id IS NULL")
    with op.batch_alter_table("custom_criterion_score_audit", naming_convention=NAMING) as batch:
        batch.alter_column("student_id", existing_type=sa.Integer(), nullable=False)
    op.execute("DELETE FROM mark_override_audit WHERE question_mark_id IS NULL")
    with op.batch_alter_table("mark_override_audit", naming_convention=NAMING) as batch:
        batch.alter_column("question_mark_id", existing_type=sa.Integer(), nullable=False)
    with op.batch_alter_table("users", naming_convention=NAMING) as batch:
        batch.drop_column("deleted_at")
        batch.drop_column("erasure_requested_at")
