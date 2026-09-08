"""Per-subject marking rules — the "AI marking agreement"

Task 2.6 (`AV-75`, `AV-111`). The tutor writes marking rules once for a subject
and they apply to every chapter, classified and piece of work in it, **in
addition to** board, level and chapter notes rather than instead of them. There
is deliberately no account-wide layer (`AV-75`).

Free text on `subjects`, not a table: one body of rules per subject, replaced
when edited, with no structure to query. Nullable because this is the one
onboarding step a tutor may skip (`AV-87`) — and an empty rule set is a real
answer, not a gap to fill.

Phase 3's context assembler consumes it under `AV-76`'s precedence; nothing
reads it before then, so this migration is additive and inert.

`batch_alter_table` with 0020's naming convention, per `DB-17`.

Revision ID: 0033
Revises: 0032
Create Date: 2026-09-08

"""

import sqlalchemy as sa

from alembic import op

NAMING = {
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
}

revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("subjects", naming_convention=NAMING) as batch:
        batch.add_column(sa.Column("marking_rules", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("subjects", naming_convention=NAMING) as batch:
        batch.drop_column("marking_rules")
