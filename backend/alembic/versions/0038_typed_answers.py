"""Typed answers, and the deterministic scan's verdict on them

Task 3.3 (`AV-73`, `AV-91`, `AV-92`, `AV-93`, `E20`). The marking pipeline takes
text where it takes images: a student may type their answers instead of
photographing them, and a typed submission auto-finalizes exactly as a
photographed one does — the trust rule does not change by channel (`AV-91`).

`typed_answer` is the student's text. `typed_flag_reason` is what the
deterministic scan found in it, and is the whole record of that control: null
means the scan ran and found nothing, which is not the same as "not scanned" —
a submission with no typed answer has nothing to scan and is null for that
reason too. Both are read together with `typed_answer`, which is what tells the
two apart.

The scan is crude and bypassable by design (`AV-93`) and is the only control in
this path that does not depend on the model's judgement about the attacker's
text. A hit sets `needs_review` on every mark in the submission and the AI's
confidence is not consulted.

`batch_alter_table` with 0020's naming convention, per `DB-17`.

Revision ID: 0038
Revises: 0037
Create Date: 2026-09-09

"""

import sqlalchemy as sa

from alembic import op

NAMING = {
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
}

revision = "0038"
down_revision = "0037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("submissions", naming_convention=NAMING) as batch:
        batch.add_column(sa.Column("typed_answer", sa.Text(), nullable=True))
        batch.add_column(sa.Column("typed_flag_reason", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("submissions", naming_convention=NAMING) as batch:
        batch.drop_column("typed_flag_reason")
        batch.drop_column("typed_answer")
