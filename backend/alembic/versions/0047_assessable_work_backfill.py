"""Every existing piece of work gets its parent row, and work_id becomes required

`0046` added `assessable_work` and an empty `work_id` on the three tables that
hold a piece of work. This fills one parent row in for every assignment, past
paper and mock that already exists, points each child at it, and then makes the
pointer required — so from here on a piece of work without a parent cannot be
written at all.

An assignment is the awkward arm: it carries neither `organization_id` nor
`subject_id`, so both are read off its `Group`. That is exactly the asymmetry
the parent table exists to remove.

Making `work_id` NOT NULL is not safe against the previous revision still
serving: Render runs `alembic upgrade head` before the new instance takes over,
so old code can write a parentless row while this is running. That fails the
ALTER, rolls the whole revision back (both engines have transactional DDL) and
fails the deploy — loudly, with nothing half-applied, and a re-run works. A
failed deploy is the intended outcome here, not something to design around
(`INF-3`, runbook R4).

The backfill loops in Python rather than running one INSERT...SELECT, because
each child needs the id of the row just inserted for it. `inserted_primary_key`
is portable across Postgres and SQLite; a single statement that fills both
sides is not. The dataset is small enough that the loop is the cheaper thing to
be sure about.

Revision ID: 0047
Revises: 0046
Create Date: 2026-09-15

"""

import sqlalchemy as sa

from alembic import op

NAMING = {
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
}

revision = "0047"
down_revision = "0046"
branch_labels = None
depends_on = None

# Stubs for the backfill only, on their own MetaData so nothing is reflected or
# created. Real `sa.Table`s rather than `sa.table()` lightweights because the
# loop needs `inserted_primary_key` — the same reason `0042` declares them.
_META = sa.MetaData()
_WORK = sa.Table(
    "assessable_work",
    _META,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("organization_id", sa.Integer),
    sa.Column("subject_id", sa.Integer),
    sa.Column("kind", sa.String),
    sa.Column("title", sa.String),
    sa.Column("created_at", sa.DateTime(timezone=True)),
)
_ASSIGNMENTS = sa.Table(
    "assignments",
    _META,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("group_id", sa.Integer),
    sa.Column("title", sa.String),
    sa.Column("work_id", sa.Integer),
    sa.Column("created_at", sa.DateTime(timezone=True)),
)
_GROUPS = sa.Table(
    "groups",
    _META,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("organization_id", sa.Integer),
    sa.Column("subject_id", sa.Integer),
)
_PAST_PAPERS = sa.Table(
    "past_papers",
    _META,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("organization_id", sa.Integer),
    sa.Column("subject_id", sa.Integer),
    sa.Column("title", sa.String),
    sa.Column("work_id", sa.Integer),
    sa.Column("created_at", sa.DateTime(timezone=True)),
)
_MOCKS = sa.Table(
    "mocks",
    _META,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("organization_id", sa.Integer),
    sa.Column("subject_id", sa.Integer),
    sa.Column("title", sa.String),
    sa.Column("work_id", sa.Integer),
    sa.Column("created_at", sa.DateTime(timezone=True)),
)


def _adopt(conn, child, kind: str, rows) -> None:
    """Give each row a parent and point it there. Skips rows that already have
    one, so a re-run after a half-finished upgrade does not double-insert."""
    for row in rows:
        if row.work_id is not None:
            continue
        work_id = conn.execute(
            _WORK.insert().values(
                organization_id=row.organization_id,
                subject_id=row.subject_id,
                kind=kind,
                title=row.title,
                created_at=row.created_at,
            )
        ).inserted_primary_key[0]
        conn.execute(child.update().where(child.c.id == row.id).values(work_id=work_id))


def upgrade() -> None:
    conn = op.get_bind()

    # An assignment's organization and subject live on its group, not on itself.
    _adopt(
        conn,
        _ASSIGNMENTS,
        "homework",
        conn.execute(
            sa.select(
                _ASSIGNMENTS.c.id,
                _ASSIGNMENTS.c.work_id,
                _ASSIGNMENTS.c.title,
                _ASSIGNMENTS.c.created_at,
                _GROUPS.c.organization_id,
                _GROUPS.c.subject_id,
            ).select_from(_ASSIGNMENTS.join(_GROUPS, _GROUPS.c.id == _ASSIGNMENTS.c.group_id))
        ).all(),
    )
    for table, kind in ((_PAST_PAPERS, "past_paper"), (_MOCKS, "mock")):
        _adopt(
            conn,
            table,
            kind,
            conn.execute(
                sa.select(
                    table.c.id,
                    table.c.work_id,
                    table.c.title,
                    table.c.created_at,
                    table.c.organization_id,
                    table.c.subject_id,
                )
            ).all(),
        )

    for name in ("assignments", "past_papers", "mocks"):
        with op.batch_alter_table(name, naming_convention=NAMING) as batch:
            batch.alter_column("work_id", existing_type=sa.Integer(), nullable=False)


def downgrade() -> None:
    # Let the pointer be empty again first, or clearing it violates NOT NULL.
    for name in ("mocks", "past_papers", "assignments"):
        with op.batch_alter_table(name, naming_convention=NAMING) as batch:
            batch.alter_column("work_id", existing_type=sa.Integer(), nullable=True)

    conn = op.get_bind()
    for table in (_MOCKS, _PAST_PAPERS, _ASSIGNMENTS):
        conn.execute(table.update().values(work_id=None))
    # Safe to empty: 0046 created this table and nothing else writes to it.
    conn.execute(_WORK.delete())
