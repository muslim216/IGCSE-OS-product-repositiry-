"""Subjects belong to a tutor's organization, and carry a level

Task 2.2 (AV-6, AV-7, AV-8, E14). Subjects were global: five seeded syllabuses,
unique on `(exam_board, code)`, shared by every tenant — `_enrolled_scope` in
`api/past_papers.py` exists because of that sharing. They are now owned, private
to the account that created them, so identity becomes unique per tenant and every
subject query filters by the caller's organization (`PROD-3`, `PROD-4`, `DB-2`,
`SEC-7`).

**The backfill assigns rather than deletes.** Every existing subject goes to the
lowest-numbered organization and every existing row gets `level = 'igcse'`. Both
are arbitrary, and both are safe here for one specific reason, confirmed with the
owner before this was written: the deployed database holds only demo and seed
data, which `python -m seed.demo` rebuilds. `E25` still applies — snapshot before
running this — because "no real users" makes an arbitrary assignment
*acceptable*, not reversible.

Deleting the old subjects instead was considered and rejected. Twenty-five
foreign keys across nine model modules point at `subjects` or `topics`, cascades
in this schema are ORM-level only (§06), and an ordered cascade hand-written
across twenty tables is a far larger risk than a wrong owner on rows nobody will
keep. The next `seed.demo` run supersedes all of it.

`level` is `igcse` for existing rows only. The **model has no default** — `AV-7`
says nothing may assume an IGCSE-shaped world, so every new subject states its
level explicitly. This backfill is the one place a value had to be invented, and
it is invented for rows that are about to be replaced.

The organizations table can legitimately be empty (a fresh database). There can
then be no users, so no groups, evidence or papers either, and the only rows that
could exist are a bare subject tree from the old seed loader. Those three tables
are cleared in FK order instead, which is the entire cascade in that case.

`batch_alter_table` with 0020's naming convention throughout, per `DB-17`.

Revision ID: 0030
Revises: 0029
Create Date: 2026-09-04

"""

import sqlalchemy as sa

from alembic import op

NAMING = {
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
}

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    with op.batch_alter_table("subjects", naming_convention=NAMING) as batch:
        batch.add_column(
            sa.Column(
                "organization_id",
                sa.Integer(),
                sa.ForeignKey("organizations.id", name="fk_subjects_organization_id_organizations"),
                nullable=True,
            )
        )
        batch.add_column(sa.Column("level", sa.String(length=16), nullable=True))

    owner = conn.execute(sa.text("SELECT MIN(id) FROM organizations")).scalar()
    if owner is None:
        # No organizations means no users, so nothing can reference these rows
        # except the subject tree itself. Clear it in FK order.
        conn.execute(sa.text("DELETE FROM topics"))
        conn.execute(sa.text("DELETE FROM chapters"))
        conn.execute(sa.text("DELETE FROM subjects"))
    else:
        conn.execute(
            sa.text("UPDATE subjects SET organization_id = :owner WHERE organization_id IS NULL"),
            {"owner": owner},
        )
    conn.execute(sa.text("UPDATE subjects SET level = 'igcse' WHERE level IS NULL"))

    # The old constraint's name has to be *discovered*, not assumed. It was
    # created unnamed by migration 0002, so each backend named it itself:
    # Postgres calls it `subjects_exam_board_code_key`, while SQLite has no name
    # for it at all until batch mode rebuilds the table and applies NAMING.
    # Hard-coding the convention name passes on SQLite and fails on Postgres with
    # `constraint ... does not exist` — `RISK-3` exactly, and how this migration
    # first failed CI.
    old_unique = _unique_constraint_named(op.get_bind(), "subjects", {"exam_board", "code"})

    with op.batch_alter_table("subjects", naming_convention=NAMING) as batch:
        batch.alter_column("organization_id", existing_type=sa.Integer(), nullable=False)
        batch.alter_column("level", existing_type=sa.String(length=16), nullable=False)
        # Global identity gives way to per-tenant identity: two tutors may each
        # teach Edexcel 4MA1. The new constraint also serves as the index for the
        # organization filter, `organization_id` being its leading column.
        # Falls back to the convention name for SQLite, where the constraint is
        # nameless until this very rebuild assigns it one from NAMING. Dropping
        # it must still happen there: batch mode carries every reflected
        # constraint into the new table, so leaving it would keep subjects
        # globally unique on (exam_board, code) and stop two tutors teaching the
        # same specification — the thing this task exists to allow.
        batch.drop_constraint(old_unique or "uq_subjects_exam_board_code", type_="unique")
        batch.create_unique_constraint(
            "uq_subjects_organization_id_exam_board_code",
            ["organization_id", "exam_board", "code"],
        )


def _unique_constraint_named(conn, table: str, columns: set[str]) -> str | None:
    """The database's own name for the unique constraint over `columns`.

    Returns None when the backend reports no name — SQLite, for an inline
    `UNIQUE (...)`. The caller then falls back to the NAMING convention name,
    which is what batch mode assigns while rebuilding the table.
    """
    for constraint in sa.inspect(conn).get_unique_constraints(table):
        if set(constraint["column_names"]) == columns:
            return constraint["name"] or None
    return None


def downgrade() -> None:
    # Going back means subjects are global again and (exam_board, code) must be
    # unique across every tenant, so two tutors teaching the same specification
    # would collide. Duplicates are removed lowest-id-wins before the constraint
    # is restored — the same rows the upgrade path treats as disposable — and
    # their topics and chapters go with them, in FK order.
    conn = op.get_bind()
    duplicates = (
        "SELECT id FROM subjects WHERE id NOT IN ("
        "  SELECT MIN(id) FROM subjects GROUP BY exam_board, code)"
    )
    conn.execute(sa.text(f"DELETE FROM topics WHERE subject_id IN ({duplicates})"))
    conn.execute(sa.text(f"DELETE FROM chapters WHERE subject_id IN ({duplicates})"))
    conn.execute(sa.text(f"DELETE FROM subjects WHERE id IN ({duplicates})"))

    with op.batch_alter_table("subjects", naming_convention=NAMING) as batch:
        batch.drop_constraint("uq_subjects_organization_id_exam_board_code", type_="unique")
        batch.create_unique_constraint("uq_subjects_exam_board_code", ["exam_board", "code"])
        batch.drop_column("level")
        batch.drop_column("organization_id")
