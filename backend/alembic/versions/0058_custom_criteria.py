"""tutor-defined custom criteria

Task 5.4b. A tutor names a criterion ("Exam technique", "Confidence") and
hand-scores each student 0-100 on it. Three new tables, no existing one
altered, so plain `op.create_table` and no batch rebuild (`DB-17` does not
apply).

Shown beside readiness, never inside it: there is no weight column and nothing
in the readiness engine reads these tables. A hand-entered number has no
evidence behind it, and letting it move a readiness score would break `PROD-1`.

**Every id in `custom_criterion_score_audit` is a plain integer.** An audit row
has to outlive what it describes: clearing a score deletes its
`custom_criterion_scores` row, and a real ForeignKey would make any delete of a
row the audit names fail on Postgres while passing every local test — the
suite runs SQLite with foreign keys off, the `RISK-3` shape this repository has
been bitten by once. Cascading instead would throw away the record of the
tutor's decision, which is what `PROD-7` exists to keep.

Nothing is backfilled: every table starts empty by construction.

Revision ID: 0058
Revises: 0057
Create Date: 2026-09-28

"""

import sqlalchemy as sa

from alembic import op

revision = "0058"
down_revision = "0057"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "custom_criteria",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey(
                "organizations.id", name="fk_custom_criteria_organization_id_organizations"
            ),
            nullable=False,
        ),
        sa.Column(
            "subject_id",
            sa.Integer(),
            sa.ForeignKey("subjects.id", name="fk_custom_criteria_subject_id_subjects"),
            nullable=True,
        ),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_by_id",
            sa.Integer(),
            sa.ForeignKey("users.id", name="fk_custom_criteria_created_by_id_users"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_custom_criteria_organization_id", "custom_criteria", ["organization_id"])

    op.create_table(
        "custom_criterion_scores",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey(
                "organizations.id", name="fk_custom_criterion_scores_organization_id_organizations"
            ),
            nullable=False,
        ),
        sa.Column(
            "student_id",
            sa.Integer(),
            sa.ForeignKey("users.id", name="fk_custom_criterion_scores_student_id_users"),
            nullable=False,
        ),
        sa.Column(
            "criterion_id",
            sa.Integer(),
            sa.ForeignKey(
                "custom_criteria.id", name="fk_custom_criterion_scores_criterion_id_custom_criteria"
            ),
            nullable=False,
        ),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "updated_by_id",
            sa.Integer(),
            sa.ForeignKey("users.id", name="fk_custom_criterion_scores_updated_by_id_users"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "student_id", "criterion_id", name="uq_custom_criterion_scores_student_id_criterion_id"
        ),
        sa.CheckConstraint(
            "score >= 0 AND score <= 100", name="ck_custom_criterion_scores_score_range"
        ),
    )

    op.create_table(
        "custom_criterion_score_audit",
        sa.Column("id", sa.Integer(), primary_key=True),
        # Integers, not ForeignKeys — see the module docstring.
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("student_id", sa.Integer(), nullable=False),
        sa.Column("criterion_id", sa.Integer(), nullable=False),
        sa.Column("old_score", sa.Integer(), nullable=True),
        sa.Column("new_score", sa.Integer(), nullable=True),
        sa.Column("changed_by_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_custom_criterion_score_audit_student_id_criterion_id",
        "custom_criterion_score_audit",
        ["student_id", "criterion_id"],
    )


def downgrade() -> None:
    # Like 0053: warn rather than refuse. Nothing else depends on these rows,
    # so proceeding cannot corrupt anything — it can only discard tutor
    # judgements and their trail, and the deploy log should say so plainly.
    bind = op.get_bind()
    for table in ("custom_criterion_scores", "custom_criterion_score_audit"):
        count = bind.execute(sa.text(f"SELECT COUNT(*) FROM {table}")).scalar_one()  # noqa: S608 - fixed table names
        if count:
            print(  # noqa: T201 - alembic's own output channel is the deploy log
                f"WARNING: dropping {count} row(s) of {table}; not recoverable after this."
            )
    op.drop_index(
        "ix_custom_criterion_score_audit_student_id_criterion_id",
        table_name="custom_criterion_score_audit",
    )
    op.drop_table("custom_criterion_score_audit")
    op.drop_table("custom_criterion_scores")
    op.drop_index("ix_custom_criteria_organization_id", table_name="custom_criteria")
    op.drop_table("custom_criteria")
