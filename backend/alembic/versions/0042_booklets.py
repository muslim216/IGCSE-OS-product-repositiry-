"""Booklets: a set of past papers, and every past paper's parent

A booklet is one uploaded document holding several whole papers; a tutor who
uploads a single paper gets a booklet of one. So `past_papers.booklet_id` is
NOT NULL — but it cannot be created that way on a table that already has rows,
hence the three-step: add it nullable, backfill a booklet per existing paper,
then tighten it.

The backfill gives each existing paper a booklet of one, `applied` because
those papers already exist (there is nothing left to extract or review), with
the paper's own file and mark scheme copied up to its booklet. `title` is left
NULL: a booklet's title is read off the document by extraction, and no such
extraction ever ran for these (`PROD-2` — absent, not fabricated).

`booklets.tutor_id` and `booklets.file_path/file_name/file_mime` are nullable
purely because their `past_papers` sources are: seed rows predate both owners
and files, and there is nothing honest to put there. Inventing an owner or a
path to satisfy a NOT NULL would be worse than the nullable column.

`batch_alter_table` with 0020's naming convention, per `DB-17` — SQLite rebuilds
`past_papers` to add the column and again to tighten it.

Revision ID: 0042
Revises: 0041
Create Date: 2026-09-13

"""

import sqlalchemy as sa

from alembic import op

NAMING = {
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
}

# Table stubs for the backfill only, on their own MetaData so nothing here is
# reflected or created. Real `sa.Table`s rather than `sa.table()` lightweights
# because the loop needs `inserted_primary_key`, which requires a declared
# primary key — and typed columns so DateTime round-trips as a datetime rather
# than a driver-specific string.
_META = sa.MetaData()
_PAST_PAPERS = sa.Table(
    "past_papers",
    _META,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("organization_id", sa.Integer),
    sa.Column("tutor_id", sa.Integer),
    sa.Column("subject_id", sa.Integer),
    sa.Column("paper_path", sa.String),
    sa.Column("paper_name", sa.String),
    sa.Column("paper_mime", sa.String),
    sa.Column("mark_scheme_path", sa.String),
    sa.Column("mark_scheme_name", sa.String),
    sa.Column("mark_scheme_mime", sa.String),
    sa.Column("created_at", sa.DateTime(timezone=True)),
)
_BOOKLETS = sa.Table(
    "booklets",
    _META,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("organization_id", sa.Integer),
    sa.Column("tutor_id", sa.Integer),
    sa.Column("subject_id", sa.Integer),
    sa.Column("title", sa.String),
    sa.Column("file_path", sa.String),
    sa.Column("file_name", sa.String),
    sa.Column("file_mime", sa.String),
    sa.Column("mark_scheme_path", sa.String),
    sa.Column("mark_scheme_name", sa.String),
    sa.Column("mark_scheme_mime", sa.String),
    sa.Column("status", sa.String),
    sa.Column("created_at", sa.DateTime(timezone=True)),
)

revision = "0042"
down_revision = "0041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "booklets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("tutor_id", sa.Integer(), nullable=True),
        sa.Column("subject_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("file_path", sa.String(length=255), nullable=True),
        sa.Column("file_name", sa.String(length=255), nullable=True),
        sa.Column("file_mime", sa.String(length=128), nullable=True),
        sa.Column("mark_scheme_path", sa.String(length=255), nullable=True),
        sa.Column("mark_scheme_name", sa.String(length=255), nullable=True),
        sa.Column("mark_scheme_mime", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("draft", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_booklets_organization_id_organizations",
        ),
        sa.ForeignKeyConstraint(["tutor_id"], ["users.id"], name="fk_booklets_tutor_id_users"),
        sa.ForeignKeyConstraint(
            ["subject_id"], ["subjects.id"], name="fk_booklets_subject_id_subjects"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_booklets_org_subject", "booklets", ["organization_id", "subject_id"])

    with op.batch_alter_table("past_papers", naming_convention=NAMING) as batch:
        batch.add_column(sa.Column("booklet_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("booklet_index", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("first_page", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("last_page", sa.Integer(), nullable=True))

    # One booklet of one per existing paper. Row by row rather than an
    # INSERT ... SELECT because each paper needs its own new booklet's id back,
    # and there is no portable way to correlate the two in bulk. These are test
    # rows only, so the loop's cost is irrelevant next to being obviously right.
    conn = op.get_bind()
    for paper in conn.execute(sa.select(_PAST_PAPERS).order_by(_PAST_PAPERS.c.id)).mappings():
        booklet_id = conn.execute(
            _BOOKLETS.insert().values(
                organization_id=paper["organization_id"],
                tutor_id=paper["tutor_id"],
                subject_id=paper["subject_id"],
                title=None,
                file_path=paper["paper_path"],
                file_name=paper["paper_name"],
                file_mime=paper["paper_mime"],
                mark_scheme_path=paper["mark_scheme_path"],
                mark_scheme_name=paper["mark_scheme_name"],
                mark_scheme_mime=paper["mark_scheme_mime"],
                status="applied",
                created_at=paper["created_at"],
            )
        ).inserted_primary_key[0]
        # Index 1: each existing paper is alone in the booklet made for it.
        # `first_page`/`last_page` stay NULL — an unsplit paper is its whole
        # document, and inventing a range would be fabricating provenance.
        conn.execute(
            sa.text("UPDATE past_papers SET booklet_id = :b, booklet_index = 1 WHERE id = :p"),
            {"b": booklet_id, "p": paper["id"]},
        )

    with op.batch_alter_table("past_papers", naming_convention=NAMING) as batch:
        batch.alter_column("booklet_id", existing_type=sa.Integer(), nullable=False)
        batch.alter_column("booklet_index", existing_type=sa.Integer(), nullable=False)
        batch.create_foreign_key(
            "fk_past_papers_booklet_id_booklets", "booklets", ["booklet_id"], ["id"]
        )
        # The key that makes re-running an approve safe (`BE-6`). `booklet_id`
        # leads it, so this also serves every "list a booklet's papers" query
        # and no separate index on `booklet_id` is warranted (`DB-12`).
        batch.create_unique_constraint(
            "uq_past_papers_booklet_id_booklet_index", ["booklet_id", "booklet_index"]
        )


def downgrade() -> None:
    with op.batch_alter_table("past_papers", naming_convention=NAMING) as batch:
        batch.drop_constraint("uq_past_papers_booklet_id_booklet_index", type_="unique")
        batch.drop_constraint("fk_past_papers_booklet_id_booklets", type_="foreignkey")
        batch.drop_column("last_page")
        batch.drop_column("first_page")
        batch.drop_column("booklet_index")
        batch.drop_column("booklet_id")
    op.drop_index("ix_booklets_org_subject", table_name="booklets")
    op.drop_table("booklets")
