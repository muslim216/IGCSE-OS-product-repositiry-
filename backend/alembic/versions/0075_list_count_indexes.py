"""list count indexes: the per-row counts on two tutor lists

Indexes only; no row is read or changed. Each serves a grouped count that
filters on a foreign key no existing index leads with (audit DB-04):

- `assignment_questions(assignment_id)`: a class's homework list counts each
  homework's questions and marks.
- `assessment_scores(assessment_id)`: the assessments list counts each one's
  scores.

Both tables are small today, so the plain build's write lock is a moment.

Revision ID: 0075
Revises: 0074
"""

from alembic import op

revision = "0075"
down_revision = "0074"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_assignment_questions_assignment_id", "assignment_questions", ["assignment_id"]
    )
    op.create_index("ix_assessment_scores_assessment_id", "assessment_scores", ["assessment_id"])


def downgrade() -> None:
    op.drop_index("ix_assessment_scores_assessment_id", table_name="assessment_scores")
    op.drop_index("ix_assignment_questions_assignment_id", table_name="assignment_questions")
