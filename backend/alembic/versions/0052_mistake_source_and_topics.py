"""mistake source and topics

`Mistake.topic_id` held exactly one topic per mistake. A question can carry
several — `QuestionTopic` (and its past-paper/mock siblings) is unique on
(question_id, topic_id), and the extractor returns a list — so one column
meant a multi-topic question was recorded against one topic chosen
arbitrarily, or skipped (decision 11). `mistake_topics` replaces it: a link
table holding every topic the question behind a mistake tests.

`Mistake.source` says who made the mistake row — the tagging job (`ai`) or a
tutor (`tutor`). 4.2's job re-runs on the same submission whenever marks
change or a tutor presses re-tag in 4.3, and it must delete what it wrote last
time without touching what a tutor decided by hand. "Delete the rows I made"
is only expressible if a row says who made it (E17, decision 8).

No data migration: `mistakes` has no writer anywhere in backend/app (verified
again for this migration, same as 0051), so it is empty in production and
there is nothing to translate. `downgrade()` refuses instead of guessing for
the same reason 0051's does — for `source`, there is no default value that is
honest about who wrote an existing row, and for `mistake_topics`, a mistake
tagged with more than one topic has nothing that fits back into a single
`topic_id` column.

Revision ID: 0052
Revises: 0051
Create Date: 2026-09-19

"""

import sqlalchemy as sa

from alembic import op

# Copied verbatim from 0051 — see DB-17.
NAMING = {
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
}

revision = "0052"
down_revision = "0051"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mistake_topics",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "mistake_id",
            sa.Integer(),
            sa.ForeignKey("mistakes.id", name="fk_mistake_topics_mistake_id_mistakes"),
            nullable=False,
        ),
        sa.Column(
            "topic_id",
            sa.Integer(),
            sa.ForeignKey("topics.id", name="fk_mistake_topics_topic_id_topics"),
            nullable=False,
        ),
        # Plain UniqueConstraint, not the functional index 0051 used — that one
        # existed to fold case on a tutor-typed name; a topic and a mistake are
        # both surrogate ids, so the columns themselves are the whole rule.
        sa.UniqueConstraint("mistake_id", "topic_id", name="uq_mistake_topics_mistake_id_topic_id"),
    )

    # `mistakes` has no writer anywhere in backend/app (checked again for this
    # migration, same grep as 0051), so `source` can be added NOT NULL with no
    # backfill. Checked here rather than left to the database for the same
    # reason 0051 checks: a NOT NULL column with no server default added to a
    # table that turned out to have rows fails on Postgres with "column
    # contains null values", mid-deploy, ahead of uvicorn starting. Either way
    # it fails closed — but a message naming the count tells whoever reads the
    # deploy log what happened, and a driver error does not.
    count = op.get_bind().execute(sa.text("SELECT COUNT(*) FROM mistakes")).scalar_one()
    if count:
        raise RuntimeError(
            f"{count} mistake(s) already exist, so `source` cannot be added NOT NULL "
            "without deciding whether each one came from the tagging job or a tutor. "
            "Back-fill them, or delete them, before running this migration — guessing "
            "who made a mistake row for them is not this migration's call (PROD-1)."
        )

    with op.batch_alter_table("mistakes", naming_convention=NAMING) as batch:
        batch.drop_column("topic_id")
        batch.add_column(
            sa.Column(
                "source",
                sa.Enum("ai", "tutor", name="mistakesource", native_enum=False, length=8),
                nullable=False,
            )
        )
        # What the tagging job (task 4) saw when a category or a question's
        # ai_feedback read like an instruction rather than data — SEC-20's
        # flag-rather-than-obey half. Nullable, no backfill needed for the same
        # reason `source` needs none: the count check above already proves the
        # table is empty.
        batch.add_column(sa.Column("note", sa.Text(), nullable=True))


def downgrade() -> None:
    conn = op.get_bind()

    # Before any DDL, for the same reason 0051's downgrade checks first: a
    # mistake's `mistake_topics` rows do not fit in one `topic_id` column once
    # there is more than one, and `source` has no honest value to fall back to
    # for a row that already exists — nothing here can say who made it.
    count = conn.execute(sa.text("SELECT COUNT(*) FROM mistakes")).scalar_one()
    if count:
        raise RuntimeError(
            f"{count} mistake(s) exist with a `source` and possibly several "
            "`mistake_topics` rows each — neither fits back into the single nullable "
            "`topic_id` column this downgrade would recreate. Delete or reassign these "
            "rows before downgrading — picking one topic out of several, or a `source` "
            "value with nothing behind it, is not this migration's call (PROD-1)."
        )

    with op.batch_alter_table("mistakes", naming_convention=NAMING) as batch:
        batch.drop_column("note")
        batch.drop_column("source")
        batch.add_column(
            sa.Column(
                "topic_id",
                sa.Integer(),
                sa.ForeignKey("topics.id", name="fk_mistakes_topic_id_topics"),
                nullable=True,
            )
        )

    op.drop_table("mistake_topics")
