"""A submission says which piece of work it answers, in one column

`submissions` is polymorphic: exactly one of `assignment_id`, `past_paper_id`
and `mock_id` is set, and every query that spans kinds has to join all three
and OR three `organization_id` columns to find out whose work it is. This adds
`work_id`, pointing at the parent row each of those three already has since
`0047`, and fills it in from whichever arm a submission uses.

Both are written from here on. The readers move onto `work_id` in D4 and D5;
the three old keys are dropped in D6, once nothing reads them. Keeping them in
step is `open_attempt`'s job — it copies `work_id` off the parent it was handed
rather than deriving it a second way.

The backfill takes each arm in turn, so a row is matched by the key it actually
has. A submission with no key at all is homework by the same rule `kind_of`
uses — Classroom sync created those before the past-paper arm existed — but it
has no assignment to take a parent from, so there is nothing to point it at.
There are none in practice (every arm's key is written at creation); if one
exists, this migration stops and says so rather than inventing a parent for it
(`PROD-1`). It stops *before* adding the column, because SQLite commits the
table rebuild that an `ALTER` needs — refusing after that would leave the column
behind and break the re-run the error asks for.

Revision ID: 0048
Revises: 0047
Create Date: 2026-09-15

"""

import sqlalchemy as sa

from alembic import op

NAMING = {
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
}

revision = "0048"
down_revision = "0047"
branch_labels = None
depends_on = None

#: Each arm: the submission column holding the key, and the table to read the
#: parent's `work_id` from.
_ARMS = (
    ("assignment_id", "assignments"),
    ("past_paper_id", "past_papers"),
    ("mock_id", "mocks"),
)


def upgrade() -> None:
    conn = op.get_bind()

    # Both checks run before any DDL, deliberately. SQLite rebuilds the table
    # to add a column, and that rebuild commits — so aborting after it leaves
    # `work_id` behind and the recovery these errors describe ("fix the rows,
    # run it again") fails on a duplicate column instead. Checking first means
    # a refusal changes nothing and the re-run is a clean first run.

    # Nothing at the database level stops a submission carrying two arms, and
    # the backfill below takes the first one it finds — assignment before past
    # paper — while `kind_of` reads past paper first. On a two-armed row those
    # two answers differ, so `work_id` would point at one piece of work while
    # every reader still on the old keys showed another.
    arm_count = " + ".join(f"(CASE WHEN {key} IS NOT NULL THEN 1 ELSE 0 END)" for key, _ in _ARMS)
    conflicted = conn.execute(
        sa.text(f"SELECT COUNT(*) FROM submissions WHERE {arm_count} > 1")  # noqa: S608
    ).scalar_one()
    if conflicted:
        raise RuntimeError(
            f"{conflicted} submission(s) carry more than one of assignment_id, past_paper_id "
            "and mock_id, so which piece of work they answer is ambiguous. Clear the wrong key "
            "on each before re-running."
        )

    # A submission with no arm at all is homework by the same rule `kind_of`
    # uses, but it has no assignment to take a parent from — and neither has
    # one whose arm points at a row that is gone. Either way there is nothing
    # to point it at, and a parent invented here would be a piece of work
    # nobody uploaded (`PROD-1`).
    has_parent = " OR ".join(
        f"({key} IS NOT NULL AND EXISTS (SELECT 1 FROM {table} p WHERE p.id = submissions.{key}))"
        for key, table in _ARMS
    )
    stranded = conn.execute(
        sa.text(f"SELECT COUNT(*) FROM submissions WHERE NOT ({has_parent})")  # noqa: S608
    ).scalar_one()
    if stranded:
        raise RuntimeError(
            f"{stranded} submission(s) have no assignment, past paper or mock to take a parent "
            "from. Give each one its arm's key before re-running."
        )

    with op.batch_alter_table("submissions", naming_convention=NAMING) as batch:
        batch.add_column(
            sa.Column(
                "work_id",
                sa.Integer(),
                sa.ForeignKey("assessable_work.id", name="fk_submissions_work_id_assessable_work"),
                nullable=True,
            )
        )

    for key, table in _ARMS:
        conn.execute(
            sa.text(
                f"UPDATE submissions SET work_id = ("  # noqa: S608 - names are from _ARMS
                f"  SELECT p.work_id FROM {table} p WHERE p.id = submissions.{key}"
                f") WHERE {key} IS NOT NULL AND work_id IS NULL"
            )
        )

    with op.batch_alter_table("submissions", naming_convention=NAMING) as batch:
        batch.alter_column("work_id", existing_type=sa.Integer(), nullable=False)

    # From D4 every cross-kind query joins submissions on this column. The
    # three old arms get their equality lookups free from their unique
    # constraints; this one has none (`DB-12`).
    op.create_index("ix_submissions_work_id", "submissions", ["work_id"])


def downgrade() -> None:
    op.drop_index("ix_submissions_work_id", table_name="submissions")
    with op.batch_alter_table("submissions", naming_convention=NAMING) as batch:
        batch.drop_column("work_id")
