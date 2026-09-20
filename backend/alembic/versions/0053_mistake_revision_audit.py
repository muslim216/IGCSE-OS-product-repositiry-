"""mistake revision audit

A tutor revising a mistake the tagging job wrote is an override of AI output,
so it leaves an append-only trail with no API to edit or delete it (`PROD-7`,
`AI-12`) — the same guarantee `mark_override_audit` gives a mark, in the table
that fits what a revision actually changes.

A new table rather than four nullable columns on `mark_override_audit`: that
one records a mark moving between two integers, this one a category and a
severity moving together, and merging them would leave every row of both kinds
half-empty with nothing in the schema saying which half means anything.

**Every id here is a plain integer, deliberately, including `mistake_id`.** An
audit row has to outlive what it describes. `services/attempts.open_attempt`
hard-deletes a submission's `Mistake` rows when a student replaces the work, so
a real ForeignKey would make that resubmission fail on Postgres while passing
every local test — the suite runs SQLite with foreign keys off, which is the
`RISK-3` shape this repository has already been bitten by once. Cascading
instead would throw away the record of the tutor's decision, which is what
`PROD-7` exists to keep.

Nothing is backfilled: this table starts empty by construction, and no existing
row anywhere records a revision that predates it.

Revision ID: 0053
Revises: 0052
Create Date: 2026-09-20

"""

import sqlalchemy as sa

from alembic import op

revision = "0053"
down_revision = "0052"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mistake_revision_audit",
        sa.Column("id", sa.Integer(), primary_key=True),
        # Integers, not ForeignKeys — see the module docstring.
        sa.Column("mistake_id", sa.Integer(), nullable=False),
        sa.Column("old_category_id", sa.Integer(), nullable=False),
        sa.Column("new_category_id", sa.Integer(), nullable=False),
        sa.Column("old_severity", sa.Integer(), nullable=False),
        sa.Column("new_severity", sa.Integer(), nullable=False),
        sa.Column(
            "changed_by_id",
            sa.Integer(),
            sa.ForeignKey("users.id", name="fk_mistake_revision_audit_changed_by_id_users"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    # Every read of this table is "what happened to this mistake", and it is
    # written far more often than read. Declared on the model too (`DB-12`).
    op.create_index(
        "ix_mistake_revision_audit_mistake_id", "mistake_revision_audit", ["mistake_id"]
    )


def downgrade() -> None:
    # Dropping the table loses the revision history, which is the one thing it
    # exists to keep. Unlike 0051 and 0052 this does not refuse on a non-empty
    # table: nothing else in the schema depends on these rows, so a downgrade
    # cannot corrupt anything by proceeding — it can only discard an audit
    # trail, and a downgrade that cannot run at all is worse than one that says
    # plainly what it is about to lose.
    count = (
        op.get_bind().execute(sa.text("SELECT COUNT(*) FROM mistake_revision_audit")).scalar_one()
    )
    if count:
        print(  # noqa: T201 - alembic's own output channel is the deploy log
            f"WARNING: dropping {count} mistake revision audit row(s); "
            "who changed which tag, and to what, is not recoverable after this."
        )
    op.drop_index("ix_mistake_revision_audit_mistake_id", table_name="mistake_revision_audit")
    op.drop_table("mistake_revision_audit")
