"""Mocks: a paper the tutor sets, the class sits and the AI marks

Task 3.4 (`AV-26`, `AV-115`, `E6`). A mock is deliberately **not** an assignment
with a flag on it — it is set, sat and marked on its own terms, so it gets its
own tables and its own arm on `Submission`.

That third arm is the cost of the independence. `submissions.mock_id` and
`question_marks.mock_question_id` join `assignment_id`/`past_paper_id` and
`question_id`/`past_paper_question_id`: exactly one of each trio is set on any
row. Which one is now read through `services/submission_kind.kind_of` rather
than re-tested at each call site, because two arms fit in an if/else and three
do not.

`EvidenceSource.mock` needs no DDL — it already exists, is stored as VARCHAR
(`DB-5`, `ADR-0007`), and already carries its weight in `SOURCE_WEIGHTS`
(`PROD-10`). A mock's marks weigh the same whether the tutor typed the score in
against an `Assessment` or the AI marked the paper.

`batch_alter_table` with 0020's naming convention, per `DB-17`.

Revision ID: 0039
Revises: 0038
Create Date: 2026-09-11

"""

import sqlalchemy as sa

from alembic import op

NAMING = {
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
}

revision = "0039"
down_revision = "0038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mocks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("tutor_id", sa.Integer(), nullable=False),
        sa.Column("subject_id", sa.Integer(), nullable=False),
        sa.Column("group_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("type", sa.String(length=8), nullable=False),
        sa.Column("sat_on", sa.Date(), nullable=True),
        sa.Column("paper_path", sa.String(length=255), nullable=False),
        sa.Column("paper_name", sa.String(length=255), nullable=False),
        sa.Column("paper_mime", sa.String(length=128), nullable=False),
        sa.Column("mark_scheme_path", sa.String(length=255), nullable=True),
        sa.Column("mark_scheme_name", sa.String(length=255), nullable=True),
        sa.Column("mark_scheme_mime", sa.String(length=128), nullable=True),
        sa.Column("total_marks", sa.Integer(), nullable=True),
        sa.Column("duration_minutes", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("extraction_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], name="fk_mocks_organization_id_organizations"
        ),
        sa.ForeignKeyConstraint(["tutor_id"], ["users.id"], name="fk_mocks_tutor_id_users"),
        sa.ForeignKeyConstraint(
            ["subject_id"], ["subjects.id"], name="fk_mocks_subject_id_subjects"
        ),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"], name="fk_mocks_group_id_groups"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "mock_questions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("mock_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("number", sa.String(length=16), nullable=False),
        sa.Column("text_summary", sa.Text(), nullable=False),
        sa.Column("max_marks", sa.Integer(), nullable=False),
        sa.Column("has_mark_scheme", sa.Boolean(), nullable=False),
        sa.Column("ai_model", sa.String(length=64), nullable=True),
        sa.Column("ai_prompt_version", sa.String(length=16), nullable=True),
        sa.ForeignKeyConstraint(["mock_id"], ["mocks.id"], name="fk_mock_questions_mock_id_mocks"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("mock_id", "number", name="uq_mock_questions_mock_id_number"),
    )
    op.create_table(
        "mock_question_topics",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("question_id", sa.Integer(), nullable=False),
        sa.Column("topic_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["question_id"],
            ["mock_questions.id"],
            name="fk_mock_question_topics_question_id_mock_questions",
        ),
        sa.ForeignKeyConstraint(
            ["topic_id"], ["topics.id"], name="fk_mock_question_topics_topic_id_topics"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "question_id", "topic_id", name="uq_mock_question_topics_question_id_topic_id"
        ),
    )
    with op.batch_alter_table("submissions", naming_convention=NAMING) as batch:
        batch.add_column(sa.Column("mock_id", sa.Integer(), nullable=True))
        batch.create_foreign_key("fk_submissions_mock_id_mocks", "mocks", ["mock_id"], ["id"])
        batch.create_unique_constraint(
            "uq_submissions_mock_id_student_id", ["mock_id", "student_id"]
        )
    with op.batch_alter_table("question_marks", naming_convention=NAMING) as batch:
        batch.add_column(sa.Column("mock_question_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_question_marks_mock_question_id_mock_questions",
            "mock_questions",
            ["mock_question_id"],
            ["id"],
        )
        batch.create_unique_constraint(
            "uq_question_marks_submission_id_mock_question_id",
            ["submission_id", "mock_question_id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("question_marks", naming_convention=NAMING) as batch:
        batch.drop_constraint("uq_question_marks_submission_id_mock_question_id", type_="unique")
        batch.drop_constraint(
            "fk_question_marks_mock_question_id_mock_questions", type_="foreignkey"
        )
        batch.drop_column("mock_question_id")
    with op.batch_alter_table("submissions", naming_convention=NAMING) as batch:
        batch.drop_constraint("uq_submissions_mock_id_student_id", type_="unique")
        batch.drop_constraint("fk_submissions_mock_id_mocks", type_="foreignkey")
        batch.drop_column("mock_id")
    op.drop_table("mock_question_topics")
    op.drop_table("mock_questions")
    op.drop_table("mocks")
