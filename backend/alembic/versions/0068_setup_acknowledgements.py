"""setup_acknowledgements: "the tutor reviewed this default" (task 9.1a)

Revision ID: 0068
Revises: 0067
"""

import sqlalchemy as sa

from alembic import op

revision = "0068"
down_revision = "0067"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "setup_acknowledgements",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey(
                "organizations.id", name="fk_setup_acknowledgements_organization_id_organizations"
            ),
            nullable=False,
        ),
        sa.Column(
            "subject_id",
            sa.Integer(),
            sa.ForeignKey("subjects.id", name="fk_setup_acknowledgements_subject_id_subjects"),
            nullable=True,
        ),
        sa.Column(
            "item",
            sa.Enum(
                "account_basics",
                "boundaries",
                "marking_rules",
                "mistake_categories",
                "weak_threshold",
                name="setupitem",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "acknowledged_by_id",
            sa.Integer(),
            sa.ForeignKey("users.id", name="fk_setup_acknowledgements_acknowledged_by_id_users"),
            nullable=False,
        ),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "organization_id",
            "subject_id",
            "item",
            name="uq_setup_acknowledgements_organization_id_subject_id_item",
        ),
    )
    # NULLs are distinct in the constraint above on both databases, so the
    # account-level row (subject_id NULL) needs this partial index to hold to one.
    op.create_index(
        "uq_setup_acknowledgements_account_item",
        "setup_acknowledgements",
        ["organization_id", "item"],
        unique=True,
        postgresql_where=sa.text("subject_id IS NULL"),
        sqlite_where=sa.text("subject_id IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_setup_acknowledgements_account_item", table_name="setup_acknowledgements")
    op.drop_table("setup_acknowledgements")
