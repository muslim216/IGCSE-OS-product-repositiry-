"""Past papers: files + questions, polymorphic submissions, attempt roll-up

Past papers gain the files and per-question structure a classified already had,
and Submission/QuestionMark become polymorphic so a student's attempt reuses the
entire marking pipeline (marking, review queue, override audit, remark requests,
evidence) rather than duplicating it.

The nullability changes on submissions.assignment_id and
question_marks.question_id are safe: every existing row has them set, and the
new columns are null for all of them.

EvidenceSource gains "past_paper" with no DDL — it is stored as VARCHAR.

Revision ID: 0020
Revises: 0019
Create Date: 2026-07-24

"""
import sqlalchemy as sa

from alembic import op

# SQLite rebuilds a whole table to add a foreign key or alter a column, which
# means every constraint on it has to be nameable — and the existing ones were
# created unnamed. This convention lets batch mode name them as it rebuilds.
NAMING = {
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
}

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("past_papers", naming_convention=NAMING) as batch:
        batch.add_column(sa.Column(
                "tutor_id",
                sa.Integer(),
                sa.ForeignKey("users.id", name="fk_past_papers_tutor_id_users"),
                nullable=True,
            ))
        batch.add_column(sa.Column("total_marks", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("duration_minutes", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("booklet_path", sa.String(length=255), nullable=True))
        batch.add_column(sa.Column("booklet_name", sa.String(length=255), nullable=True))
        batch.add_column(sa.Column("booklet_mime", sa.String(length=128), nullable=True))
        batch.add_column(sa.Column("mark_scheme_path", sa.String(length=255), nullable=True))
        batch.add_column(sa.Column("mark_scheme_name", sa.String(length=255), nullable=True))
        batch.add_column(sa.Column("mark_scheme_mime", sa.String(length=128), nullable=True))
        batch.add_column(sa.Column("extraction_error", sa.Text(), nullable=True))

    op.create_table(
        "past_paper_questions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "past_paper_id", sa.Integer(), sa.ForeignKey("past_papers.id"), nullable=False
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("number", sa.String(length=16), nullable=False),
        sa.Column("text_summary", sa.Text(), nullable=False),
        sa.Column("max_marks", sa.Integer(), nullable=False),
        sa.Column("has_mark_scheme", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("ai_model", sa.String(length=64), nullable=True),
        sa.Column("ai_prompt_version", sa.String(length=16), nullable=True),
        sa.UniqueConstraint("past_paper_id", "number"),
    )

    op.create_table(
        "past_paper_question_topics",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "question_id",
            sa.Integer(),
            sa.ForeignKey("past_paper_questions.id"),
            nullable=False,
        ),
        sa.Column("topic_id", sa.Integer(), sa.ForeignKey("topics.id"), nullable=False),
        sa.UniqueConstraint("question_id", "topic_id"),
    )

    # A submission is now for either an assignment or a past paper.
    with op.batch_alter_table("submissions", naming_convention=NAMING) as batch:
        batch.alter_column("assignment_id", existing_type=sa.Integer(), nullable=True)
        batch.add_column(
            sa.Column(
                "past_paper_id",
                sa.Integer(),
                sa.ForeignKey("past_papers.id", name="fk_submissions_past_paper_id_past_papers"),
                nullable=True,
            )
        )
        batch.add_column(
            sa.Column("timed", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch.add_column(sa.Column("time_taken_minutes", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("attempted_at", sa.Date(), nullable=True))
        batch.create_unique_constraint(
            "uq_submissions_past_paper_student", ["past_paper_id", "student_id"]
        )

    with op.batch_alter_table("question_marks", naming_convention=NAMING) as batch:
        batch.alter_column("question_id", existing_type=sa.Integer(), nullable=True)
        batch.add_column(
            sa.Column(
                "past_paper_question_id",
                sa.Integer(),
                sa.ForeignKey(
                    "past_paper_questions.id",
                    name="fk_question_marks_pp_question_id_past_paper_questions",
                ),
                nullable=True,
            )
        )
        batch.create_unique_constraint(
            "uq_question_marks_submission_pp_question",
            ["submission_id", "past_paper_question_id"],
        )

    # The attempt row becomes a roll-up filled in when the submission settles,
    # so raw_marks starts null and the self-declared time is recorded.
    with op.batch_alter_table("past_paper_attempts", naming_convention=NAMING) as batch:
        batch.alter_column("raw_marks", existing_type=sa.Integer(), nullable=True)
        batch.add_column(sa.Column("time_taken_minutes", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("past_paper_attempts", naming_convention=NAMING) as batch:
        batch.drop_column("time_taken_minutes")
        batch.alter_column("raw_marks", existing_type=sa.Integer(), nullable=False)

    with op.batch_alter_table("question_marks", naming_convention=NAMING) as batch:
        batch.drop_constraint("uq_question_marks_submission_pp_question", type_="unique")
        batch.drop_column("past_paper_question_id")
        batch.alter_column("question_id", existing_type=sa.Integer(), nullable=False)

    with op.batch_alter_table("submissions", naming_convention=NAMING) as batch:
        batch.drop_constraint("uq_submissions_past_paper_student", type_="unique")
        batch.drop_column("attempted_at")
        batch.drop_column("time_taken_minutes")
        batch.drop_column("timed")
        batch.drop_column("past_paper_id")
        batch.alter_column("assignment_id", existing_type=sa.Integer(), nullable=False)

    op.drop_table("past_paper_question_topics")
    op.drop_table("past_paper_questions")

    with op.batch_alter_table("past_papers", naming_convention=NAMING) as batch:
        for column in (
            "extraction_error",
            "mark_scheme_mime",
            "mark_scheme_name",
            "mark_scheme_path",
            "booklet_mime",
            "booklet_name",
            "booklet_path",
            "duration_minutes",
            "total_marks",
            "tutor_id",
        ):
            batch.drop_column(column)
