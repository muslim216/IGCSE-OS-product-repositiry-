"""narratives — the precomputed tutor-class and parent-child paragraphs

Spec §8 is absolute for the tutor's home: the narrative is present when the
surface opens; no primary surface waits on a model to render its primary
content. Today POST /groups/{id}/brief blocks on a live model call and persists
nothing but an AiUsageEvent. This table is where the generated text now lives so
a read is a seek, not an AI call.

Append-only: a refresh writes a new row, the read takes the latest. The two
nullable FKs (group_id, student_id) are selected by `audience` — a native ENUM
is deliberately avoided (native_enum=False in the model) so a third audience
later needs no migration. No reviewed_at / suppressed columns: there is no
review step (D2).

The three indexes are created here AND declared on the model (DB-12): four of
the five pre-existing indexes in this schema live only in migrations, so the
test schema already differs from production — this table does not add a fifth
divergence. This is a create_table, so no batch_alter_table and no naming
convention are involved, and nothing holds an FK to `narratives`, so the
downgrade is a clean drop_table (verified up -> down -> up).

Revision ID: 0023
Revises: 0022
Create Date: 2026-08-11

"""

import sqlalchemy as sa

from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "narratives",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey("organizations.id"),
            nullable=False,
        ),
        # Stored as VARCHAR (native_enum=False in the model): adding a third
        # audience never needs DDL.
        sa.Column("audience", sa.String(length=16), nullable=False),
        sa.Column("group_id", sa.Integer(), sa.ForeignKey("groups.id"), nullable=True),
        sa.Column("student_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("prompt_version", sa.String(length=16), nullable=False),
        sa.Column("model", sa.String(length=64), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        # Exactly one target. The model's `target_id` accessor enforces the
        # audience/FK pairing on read; this rejects a row with both FKs set or
        # both null at the write, where the failure still points at its cause.
        # Named explicitly so the downgrade and any future ALTER can address it
        # (DB-17) — and audience-agnostic, so a third audience still needs no DDL.
        sa.CheckConstraint(
            "(group_id IS NULL) <> (student_id IS NULL)",
            name="ck_narratives_exactly_one_target",
        ),
    )
    op.create_index("ix_narratives_org", "narratives", ["organization_id"])
    op.create_index("ix_narratives_org_group", "narratives", ["organization_id", "group_id", "id"])
    op.create_index(
        "ix_narratives_org_student", "narratives", ["organization_id", "student_id", "id"]
    )


def downgrade() -> None:
    op.drop_index("ix_narratives_org_student", table_name="narratives")
    op.drop_index("ix_narratives_org_group", table_name="narratives")
    op.drop_index("ix_narratives_org", table_name="narratives")
    op.drop_table("narratives")
