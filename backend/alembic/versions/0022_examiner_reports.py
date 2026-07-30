"""examiner_reports — the board's published report for one paper sitting

A shared library, deliberately global where the rest of the past-paper world is
not. Papers, booklets and mark schemes carry organization_id precisely so one
tutor's upload cannot reach another tutor's students. An examiner report is a
public board document rather than a tutor's own compilation, and the collection
is meant to be built up once for everybody, so it has no organization_id and
any tutor's past paper can match it.

That sharing has a cost worth naming: one wrong upload changes marking for every
organization at once. The unique constraint on (subject, paper, session) makes
the first upload win rather than letting later ones silently overwrite, and
uploaded_by_tutor_id records who may replace or remove it.

uploaded_by_tutor_id is nullable so removing a user account does not take the
library's rows with it; the row simply becomes admin-only to change.

Revision ID: 0022
Revises: 0021
Create Date: 2026-07-30

"""
from alembic import op
import sqlalchemy as sa

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "examiner_reports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("subject_id", sa.Integer(), sa.ForeignKey("subjects.id"), nullable=False),
        sa.Column("paper_number", sa.String(length=32), nullable=False),
        sa.Column("session_label", sa.String(length=64), nullable=False),
        sa.Column("file_path", sa.String(length=255), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("file_mime", sa.String(length=128), nullable=False),
        sa.Column(
            "uploaded_by_tutor_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("subject_id", "paper_number", "session_label"),
    )


def downgrade() -> None:
    op.drop_table("examiner_reports")
