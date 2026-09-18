"""mistake categories become a tutor-owned table

The five-member MistakeCategory enum said every tutor of every subject sorts
mistakes the same way. They do not, and a tutor who disagreed had nothing to
change. The table is scoped per (organization, subject) like grade_boundaries,
and a category in use is archived rather than deleted so already-tagged
mistakes keep reading back.

No data migration: nothing in backend/app has ever written a `mistakes` row,
so there is no enum value to translate. `downgrade()` therefore refuses rather
than guessing which enum member a tutor's own category was.

Revision ID: 0051
Revises: 0050
Create Date: 2026-09-18

"""

import sqlalchemy as sa

from alembic import op

# Copied verbatim from 0050 — see DB-17.
NAMING = {
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
}

revision = "0051"
down_revision = "0050"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mistake_categories",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False
        ),
        sa.Column("subject_id", sa.Integer(), sa.ForeignKey("subjects.id"), nullable=False),
        sa.Column("name", sa.String(length=60), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "organization_id",
            "subject_id",
            "name",
            name="uq_mistake_categories_organization_id_subject_id_name",
        ),
    )

    # `mistakes` has no writer anywhere in backend/app (verified by grep before
    # this migration was written) and is therefore empty, so the enum column
    # can be dropped and the new FK added NOT NULL in the same batch with no
    # backfill.
    with op.batch_alter_table("mistakes", naming_convention=NAMING) as batch:
        batch.drop_column("category")
        batch.add_column(
            sa.Column(
                "category_id",
                sa.Integer(),
                sa.ForeignKey(
                    "mistake_categories.id",
                    name="fk_mistakes_category_id_mistake_categories",
                ),
                nullable=False,
            )
        )


def downgrade() -> None:
    conn = op.get_bind()

    # Before any DDL, for the same reason 0049's downgrade checks first: a
    # tutor's own category name has no enum member to become, so there is
    # nothing honest to put in a recreated `category` column for a row that
    # already has one.
    count = conn.execute(sa.text("SELECT COUNT(*) FROM mistakes")).scalar_one()
    if count:
        raise RuntimeError(
            f"{count} mistake(s) are tagged with a tutor-owned category that has no enum "
            "member to become. Delete or reassign these rows before downgrading — deciding "
            "which enum value stands in for a tutor's own word is not this migration's call "
            "(PROD-1)."
        )

    with op.batch_alter_table("mistakes", naming_convention=NAMING) as batch:
        batch.drop_column("category_id")
        batch.add_column(
            sa.Column(
                "category",
                sa.Enum(
                    "misread",
                    "content_gap",
                    "careless",
                    "calculation",
                    "time_management",
                    name="mistakecategory",
                    native_enum=False,
                    length=16,
                ),
                nullable=False,
            )
        )

    op.drop_table("mistake_categories")
