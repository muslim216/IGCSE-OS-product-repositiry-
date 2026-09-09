"""The summarised form of a subject's marking rules, which is what marking reads

Task 3.2c (`AV-75`, owner's instruction of 9 Sep 2026: the subject's rules are
summarised and the AI uses the summary). The tutor's full text stays in
`marking_rules` and is the thing they own and edit; this column holds what the
marking prompt is actually given.

Nullable, and **null is a working state, not a gap**: `build_marking_context`
falls back to the full text whenever the summary is absent. That is what makes
the window between a tutor saving and the job finishing correct rather than a
period in which their rules silently do not apply — and it is what a permanently
failing summarisation degrades to, at a cost, instead of dropping the rules.

Writing `marking_rules` clears this column in the same statement, so a summary
can be absent or current but never stale. There is deliberately no fingerprint
column to compare: "clear it and rebuild" cannot drift the way "compare and
decide" can.

`batch_alter_table` with 0020's naming convention, per `DB-17`.

Revision ID: 0036
Revises: 0035
Create Date: 2026-09-09

"""

import sqlalchemy as sa

from alembic import op

NAMING = {
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
}

revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("subjects", naming_convention=NAMING) as batch:
        batch.add_column(sa.Column("marking_rules_summary", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("subjects", naming_convention=NAMING) as batch:
        batch.drop_column("marking_rules_summary")
