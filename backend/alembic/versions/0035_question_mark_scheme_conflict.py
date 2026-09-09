"""Record where a tutor's rule overrode the official mark scheme

Task 3.2 (`AV-76`, as revised by the owner on 9 Sep 2026). `AV-76` and `AV-94`
originally made the official mark scheme absolute. The owner reversed that: a
tutor's marking rule beats the scheme, the marks are awarded the tutor's way,
and **the fact that the scheme contradicts is recorded**. This column is that
record.

Nullable and null for the overwhelming majority of marks: null means no tutor
rule changed this mark, which is the ordinary case and must not be confused
with "we did not check" (`PROD-2`). Free text rather than a flag because the
useful part is *what* the scheme required and *which* rule overrode it — a
boolean would tell a tutor that something happened and nothing about what.

It sits on `question_marks` next to the other AI-drafted fields rather than in
an audit table: it is part of the draft the model produced, replaced when a
submission is re-marked, exactly as `ai_feedback` is (`BE-6`). `MarkOverrideAudit`
remains what it was — the append-only record of a *tutor* overriding the AI.

`batch_alter_table` with 0020's naming convention, per `DB-17`.

Revision ID: 0035
Revises: 0034
Create Date: 2026-09-09

"""

import sqlalchemy as sa

from alembic import op

NAMING = {
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
}

revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("question_marks", naming_convention=NAMING) as batch:
        batch.add_column(sa.Column("scheme_conflict", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("question_marks", naming_convention=NAMING) as batch:
        batch.drop_column("scheme_conflict")
