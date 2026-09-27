"""per-subject readiness factor config and per-factor on/off

Task 5.4a. `readiness_weights` gains a nullable `subject_id`: NULL is the
organization's account row, a value is that subject's override, and the
override replaces the account row whole (decision 8). Beside every
`weight_<factor>` sits an `enabled_<factor>` switch, default true, so every
existing row keeps all six factors counting.

Uniqueness moves from `UNIQUE(organization_id)` to
`UNIQUE(organization_id, subject_id)` plus a partial unique index on
`organization_id WHERE subject_id IS NULL`. The constraint alone cannot hold
the account row to one per organization: Postgres treats NULLs as distinct,
so two NULL-subject rows both pass it (RISK-3).

The old constraint was created unnamed in 0016 (`unique=True` on the column),
so its name differs by dialect: Postgres named it
`readiness_weights_organization_id_key`; on SQLite the batch rebuild reflects
it and names it through NAMING (`uq_readiness_weights_organization_id`).

`batch_alter_table` with the naming convention from 0020 and an explicitly
named FK, per `DB-17`.

Downgrade DELETES every subject-scoped row before restoring
`UNIQUE(organization_id)` — the old schema has nowhere to hold an override,
so per-subject configs are lost on downgrade. Account rows survive, their
switches dropped (every factor counts again).

Revision ID: 0057
Revises: 0056
Create Date: 2026-09-28

"""

import sqlalchemy as sa

from alembic import op

revision = "0057"
down_revision = "0056"
branch_labels = None
depends_on = None

NAMING = {
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
}

FACTORS = (
    "topic_mastery",
    "past_paper_performance",
    "homework_performance",
    "assessment_performance",
    "syllabus_coverage",
    "mistake_analysis",
)
FK_NAME = "fk_readiness_weights_subject_id_subjects"
UQ_SCOPE = "uq_readiness_weights_organization_id_subject_id"
ACCOUNT_ROW_INDEX = "uq_readiness_weights_account_row"


def _old_unique_name() -> str:
    if op.get_bind().dialect.name == "postgresql":
        return "readiness_weights_organization_id_key"
    return "uq_readiness_weights_organization_id"


def upgrade() -> None:
    old_unique = _old_unique_name()
    with op.batch_alter_table("readiness_weights", naming_convention=NAMING) as batch:
        batch.drop_constraint(old_unique, type_="unique")
        batch.add_column(sa.Column("subject_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(FK_NAME, "subjects", ["subject_id"], ["id"])
        for factor in FACTORS:
            batch.add_column(
                sa.Column(
                    f"enabled_{factor}", sa.Boolean(), nullable=False, server_default=sa.true()
                )
            )
        batch.create_unique_constraint(UQ_SCOPE, ["organization_id", "subject_id"])
    op.create_index(
        ACCOUNT_ROW_INDEX,
        "readiness_weights",
        ["organization_id"],
        unique=True,
        postgresql_where=sa.text("subject_id IS NULL"),
        sqlite_where=sa.text("subject_id IS NULL"),
    )


def downgrade() -> None:
    old_unique = _old_unique_name()
    op.drop_index(ACCOUNT_ROW_INDEX, table_name="readiness_weights")
    # Overrides have nowhere to live in the old schema, and would violate the
    # restored UNIQUE(organization_id) beside their account row.
    op.execute("DELETE FROM readiness_weights WHERE subject_id IS NOT NULL")
    with op.batch_alter_table("readiness_weights", naming_convention=NAMING) as batch:
        batch.drop_constraint(UQ_SCOPE, type_="unique")
        batch.drop_constraint(FK_NAME, type_="foreignkey")
        for factor in FACTORS:
            batch.drop_column(f"enabled_{factor}")
        batch.drop_column("subject_id")
        batch.create_unique_constraint(old_unique, ["organization_id"])
