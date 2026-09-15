"""A submission names one piece of work, and only that

`submissions` carried three nullable foreign keys — `assignment_id`,
`past_paper_id`, `mock_id` — with exactly one set, and that arm decided both
what kind of work the submission answered and whose it was. Reading the wrong
one raised inside an authorization check; every query that spanned kinds had to
join all three and OR three `organization_id` columns, and an arm left out of
one of those ORs vanished from that query in silence. `0046`–`0048` built the
parent row that answers both questions, and D4/D5 moved every reader onto it.
Nothing reads the three keys now, so they go.

The three per-arm unique constraints go with them, replaced by one on
(`work_id`, `student_id`). That is stricter, not weaker: three constraints, one
per key, could not stop the same student holding two submissions against a
single piece of work through two different keys. It is also the index
`work_id` lookups use, so `ix_submissions_work_id` is dropped as redundant
rather than left as a second copy of the same leading column.

A duplicate would make the new constraint fail on the ALTER, which on Postgres
rolls the whole migration back mid-deploy. This checks for them first and says
how many, so the failure names the rows instead of a constraint.

The downgrade rebuilds the three columns from `work_id` — each child table has
a unique `work_id`, so every submission's arm can be worked out again — and
restores the three constraints.

Revision ID: 0049
Revises: 0048
Create Date: 2026-09-15

"""

import sqlalchemy as sa

from alembic import op

NAMING = {
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
}

revision = "0049"
down_revision = "0048"
branch_labels = None
depends_on = None

#: Each arm: the submission column that held the key, and the table to read it
#: back from on a downgrade.
_ARMS = (
    ("assignment_id", "assignments"),
    ("past_paper_id", "past_papers"),
    ("mock_id", "mocks"),
)

#: The unique constraints being replaced, by the columns they cover, with the
#: name this repo's convention would give them. Two were created by name and
#: match; `(assignment_id, student_id)` was written unnamed inside the
#: `create_table` in `0003`, so Postgres called it
#: `submissions_assignment_id_student_id_key` and dropping the convention name
#: would abort the deploy. `_uq_name` below asks the database instead of
#: assuming — the class of bug `RISK-3` exists for, and one SQLite cannot show
#: because its batch rebuild fabricates whatever name the convention asks for.
_OLD_UNIQUES = (
    (("assignment_id", "student_id"), "uq_submissions_assignment_id_student_id"),
    (("past_paper_id", "student_id"), "uq_submissions_past_paper_student"),
    (("mock_id", "student_id"), "uq_submissions_mock_id_student_id"),
)


def _uq_name(inspector, columns: tuple[str, ...], convention_name: str) -> str | None:
    """What this database actually calls the unique constraint over `columns`.

    `None` means there is none to drop. A reflected constraint with no name is
    SQLite's unnamed one; the batch rebuild names it from the convention, so
    that is the name to hand back.
    """
    for constraint in inspector.get_unique_constraints("submissions"):
        if sorted(constraint["column_names"]) == sorted(columns):
            return constraint["name"] or convention_name
    return None


def upgrade() -> None:
    conn = op.get_bind()

    # Before any DDL: SQLite commits the table rebuild an ALTER needs, so a
    # refusal afterwards would leave the table half-changed and break the
    # re-run this message asks for.
    duplicates = conn.execute(
        sa.text(
            "SELECT COUNT(*) FROM (SELECT work_id, student_id FROM submissions "
            "GROUP BY work_id, student_id HAVING COUNT(*) > 1) d"
        )
    ).scalar_one()
    if duplicates:
        raise RuntimeError(
            f"{duplicates} (work_id, student_id) pair(s) have more than one submission, so "
            "one attempt per student per piece of work cannot be enforced yet. Merge or delete "
            "the extra rows before re-running — deciding which attempt counts is not this "
            "migration's call (PROD-1)."
        )

    inspector = sa.inspect(conn)
    old_uniques = [
        name
        for columns, convention_name in _OLD_UNIQUES
        if (name := _uq_name(inspector, columns, convention_name)) is not None
    ]

    op.drop_index("ix_submissions_work_id", table_name="submissions")
    with op.batch_alter_table("submissions", naming_convention=NAMING) as batch:
        for name in old_uniques:
            batch.drop_constraint(name, type_="unique")
        for key, _ in _ARMS:
            batch.drop_column(key)
        batch.create_unique_constraint(
            "uq_submissions_work_id_student_id", ["work_id", "student_id"]
        )


def downgrade() -> None:
    with op.batch_alter_table("submissions", naming_convention=NAMING) as batch:
        batch.drop_constraint("uq_submissions_work_id_student_id", type_="unique")
        for key, table in _ARMS:
            batch.add_column(
                sa.Column(
                    key,
                    sa.Integer(),
                    sa.ForeignKey(f"{table}.id", name=f"fk_submissions_{key}_{table}"),
                    nullable=True,
                )
            )

    conn = op.get_bind()
    for key, table in _ARMS:
        conn.execute(
            sa.text(
                f"UPDATE submissions SET {key} = ("  # noqa: S608 - names are from _ARMS
                f"  SELECT p.id FROM {table} p WHERE p.work_id = submissions.work_id"
                f")"
            )
        )

    with op.batch_alter_table("submissions", naming_convention=NAMING) as batch:
        batch.create_unique_constraint(
            "uq_submissions_assignment_id_student_id", ["assignment_id", "student_id"]
        )
        batch.create_unique_constraint(
            "uq_submissions_past_paper_student", ["past_paper_id", "student_id"]
        )
        batch.create_unique_constraint(
            "uq_submissions_mock_id_student_id", ["mock_id", "student_id"]
        )
    op.create_index("ix_submissions_work_id", "submissions", ["work_id"])
