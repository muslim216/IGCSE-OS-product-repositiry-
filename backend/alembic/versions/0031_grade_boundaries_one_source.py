"""One source for grade boundaries: drop subjects.grade_boundaries

Task 2.4 (AV-11). Two sources existed and disagreed (`RISK-5`): the JSON column
on `subjects`, read by the v1 engine, reports and the class strip, and the
org-scoped `grade_boundaries` table read by v2. Same subject, two answers, and
nothing said which one a screen was showing.

The table wins, so the column goes. What a subject carried is **copied into the
table first**, for the subject's own organization — the column stopped being
global in task 2.2, when subjects became tenant-owned, so this copy is exact
rather than a guess about who the numbers belonged to. An organization that has
already set its own boundaries for a subject keeps them: its rows are the
tutor's, and the column's are whatever the syllabus extractor seeded.

After this, a subject with no rows in `grade_boundaries` has **no predicted
grade** anywhere in the product, which is the point (`PROD-2`, `PROD-6`) — the
editor offers the published split for its scale and it counts once the tutor
saves it.

`downgrade()` re-creates the column and refills it from each subject's own
organization's rows, so up → down → up round-trips the single-organization case
this schema has ever had. Two exceptions, both only reachable from data the
editor cannot produce: a subject whose boundaries differ *between* two
organizations cannot fit in one JSON column — the whole reason the column is
going — and a grade label longer than `grade_label`'s 16 characters is truncated
on the way in (`GradeBand` caps at 16, so nothing a tutor saved can hit this).

`batch_alter_table` with 0020's naming convention, per `DB-17`.

Revision ID: 0031
Revises: 0030
Create Date: 2026-09-08

"""

import json

import sqlalchemy as sa

from alembic import op

NAMING = {
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
}

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def _bands(raw) -> list[dict]:
    """The column's value as a list of bands, whatever the driver handed back.

    SQLite stores the JSON column as TEXT and returns a string; Postgres returns
    the decoded object. Anything else — NULL, a scalar, a malformed string — is
    no boundaries rather than an exception mid-migration.
    """
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return []
    # `json.loads("42")` is an int, and iterating one raises rather than
    # migrating (CodeRabbit). Anything that is not a list of bands is no
    # boundaries, which is what the docstring already promised.
    if not isinstance(raw, list):
        return []
    bands = []
    for b in raw:
        if not isinstance(b, dict) or "grade" not in b or "min" not in b:
            continue
        try:
            minimum = float(b["min"])
        except (TypeError, ValueError):
            # A band whose cut-off is not a number ("90%", None) is not a band.
            # Skipping it keeps the promise above; letting float() raise inside
            # the loop would abort the whole migration (cubic).
            continue
        bands.append({"grade": b["grade"], "min": minimum})
    return bands


def upgrade() -> None:
    conn = op.get_bind()

    taken = {
        (row.organization_id, row.subject_id)
        for row in conn.execute(
            sa.text("SELECT DISTINCT organization_id, subject_id FROM grade_boundaries")
        )
    }
    for row in conn.execute(sa.text("SELECT id, organization_id, grade_boundaries FROM subjects")):
        if (row.organization_id, row.id) in taken:
            continue
        seen: set[str] = set()
        for band in _bands(row.grade_boundaries):
            label = str(band["grade"])[:16]
            # (organization, subject, grade_label) is unique. A column holding
            # the same grade twice is malformed either way; keeping the first is
            # what predict_grade would have done, since it walks top to bottom.
            if label in seen:
                continue
            seen.add(label)
            conn.execute(
                sa.text(
                    "INSERT INTO grade_boundaries"
                    " (organization_id, subject_id, grade_label, min_percentage)"
                    " VALUES (:org, :subject, :label, :min)"
                ),
                {
                    "org": row.organization_id,
                    "subject": row.id,
                    "label": label,
                    "min": band["min"],
                },
            )

    with op.batch_alter_table("subjects", naming_convention=NAMING) as batch:
        batch.drop_column("grade_boundaries")


def downgrade() -> None:
    conn = op.get_bind()

    # NOT NULL on a table with rows needs a server default to land; it is dropped
    # again below so the restored column matches what the model declared.
    with op.batch_alter_table("subjects", naming_convention=NAMING) as batch:
        batch.add_column(
            sa.Column("grade_boundaries", sa.JSON(), nullable=False, server_default="[]")
        )

    for row in conn.execute(sa.text("SELECT id, organization_id FROM subjects")):
        bands = [
            {"grade": b.grade_label, "min": b.min_percentage}
            for b in conn.execute(
                sa.text(
                    "SELECT grade_label, min_percentage FROM grade_boundaries"
                    " WHERE organization_id = :org AND subject_id = :subject"
                    " ORDER BY min_percentage DESC"
                ),
                {"org": row.organization_id, "subject": row.id},
            )
        ]
        if bands:
            conn.execute(
                sa.text("UPDATE subjects SET grade_boundaries = :bands WHERE id = :id"),
                {"bands": json.dumps(bands), "id": row.id},
            )

    with op.batch_alter_table("subjects", naming_convention=NAMING) as batch:
        batch.alter_column("grade_boundaries", existing_type=sa.JSON(), server_default=None)
