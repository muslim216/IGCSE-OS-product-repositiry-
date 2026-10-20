"""hot lookup indexes: the per-student reads and sign-in lookups that scanned

Indexes only; no row is read or changed. Each serves a query that filters on
columns no existing index leads with:

- `submissions(student_id, status)`: readiness, averaging, mistakes and the
  activity poll read a student's settled work without `work_id`.
- `submission_files(submission_id)`: every load of a submission's pages.
- `evidence(source_ref)`: re-settling a submission deletes its old evidence.
- `ai_usage_events(organization_id, created_at)`: the usage page.
- `notifications(organization_id, created_at)`: the undelivered list.
- `group_members(student_id)`: which classes a student is in.
- `lower(email)` and `lower(username)` on `users`, unique: sign-in and sign-up
  compare the folded value, which the plain unique columns cannot serve. Every
  writer in the code has lowercased both since the first release, so no pair
  of rows it wrote can collide; a row put in by hand could, and would fail this
  migration loudly (it rolls back and the previous release keeps serving).

A plain build locks each table against writes while it runs. Every table is
small today, so that is a moment; on a large table this would need
`CREATE INDEX CONCURRENTLY` outside a transaction instead.

Revision ID: 0073
Revises: 0072
"""

import sqlalchemy as sa

from alembic import op

revision = "0073"
down_revision = "0072"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_submissions_student_id_status", "submissions", ["student_id", "status"])
    op.create_index("ix_submission_files_submission_id", "submission_files", ["submission_id"])
    op.create_index("ix_evidence_source_ref", "evidence", ["source_ref"])
    op.create_index(
        "ix_ai_usage_events_organization_id_created_at",
        "ai_usage_events",
        ["organization_id", "created_at"],
    )
    op.create_index(
        "ix_notifications_organization_id_created_at",
        "notifications",
        ["organization_id", "created_at"],
    )
    op.create_index("ix_group_members_student_id", "group_members", ["student_id"])
    op.create_index("uq_users_lower_email", "users", [sa.text("lower(email)")], unique=True)
    op.create_index("uq_users_lower_username", "users", [sa.text("lower(username)")], unique=True)


def downgrade() -> None:
    op.drop_index("uq_users_lower_username", table_name="users")
    op.drop_index("uq_users_lower_email", table_name="users")
    op.drop_index("ix_group_members_student_id", table_name="group_members")
    op.drop_index("ix_notifications_organization_id_created_at", table_name="notifications")
    op.drop_index("ix_ai_usage_events_organization_id_created_at", table_name="ai_usage_events")
    op.drop_index("ix_evidence_source_ref", table_name="evidence")
    op.drop_index("ix_submission_files_submission_id", table_name="submission_files")
    op.drop_index("ix_submissions_student_id_status", table_name="submissions")
