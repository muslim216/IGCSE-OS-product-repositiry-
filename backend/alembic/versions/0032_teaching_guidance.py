"""Teaching guidance: the second per-subject setup document

Task 2.5 (`AV-10`). A tutor uploads a syllabus *and* a scheme of work / teaching
guidance per subject. Phase 6 reads the second one to judge which chapters are
harder or slower and weights the plan's time accordingly (`AV-14`); until then
it is stored and served, never parsed.

Four nullable columns on `subjects` rather than a table: one document per
subject, replaced rather than versioned, and with no processing state of its own
— which is the thing that makes `syllabus_uploads` a table. All four are written
and cleared together; `guidance_path` is the object key in the Phase 1
`StorageService`, the rest is what a download needs to name and type the file.

Additive and nullable, so `downgrade()` simply drops them. The stored objects
themselves are not deleted by a downgrade — an orphaned upload is recoverable,
a deleted one is not, and the orphan sweep in the storage roadmap is where
unreferenced objects are collected.

`batch_alter_table` with 0020's naming convention, per `DB-17`.

Revision ID: 0032
Revises: 0031
Create Date: 2026-09-08

"""

import sqlalchemy as sa

from alembic import op

NAMING = {
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
}

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("subjects", naming_convention=NAMING) as batch:
        batch.add_column(sa.Column("guidance_path", sa.String(length=255), nullable=True))
        batch.add_column(sa.Column("guidance_name", sa.String(length=255), nullable=True))
        batch.add_column(sa.Column("guidance_mime", sa.String(length=128), nullable=True))
        batch.add_column(
            sa.Column("guidance_uploaded_at", sa.DateTime(timezone=True), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("subjects", naming_convention=NAMING) as batch:
        batch.drop_column("guidance_uploaded_at")
        batch.drop_column("guidance_mime")
        batch.drop_column("guidance_name")
        batch.drop_column("guidance_path")
