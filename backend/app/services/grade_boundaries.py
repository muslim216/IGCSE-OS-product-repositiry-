"""Where a subject's grade boundaries come from — one source, and this module.

**The org-scoped `GradeBoundary` table is the only source** (`AV-11`, task 2.4).
`Subject.grade_boundaries` used to sit behind it as a global default and is gone:
the column is dropped, and with it `RISK-5`'s two-sources-disagreeing problem.

The consequence is deliberate. **A subject whose organization has set no
boundaries has no predicted grade** — every surface shows the absence and the
control that fixes it, never a grade mapped through numbers nobody entered
(`PROD-2`, `PROD-6`). Nothing in the product invents one.

**Defaults are offered, never written.** `defaults_for_scale` is what the editor
pre-fills so a new tutor is not made to type ten numbers before anything works;
it is labelled unconfirmed wherever shown (`PROD-8`) and becomes real only when
the tutor saves it. Writing it on their behalf would make a published guess
indistinguishable from their own figures.

Scoping is per organization because boundaries are per organization: a subject is
owned by one tenant since task 2.2, but two tutors sharing an organization share
these numbers, and no tenant may ever move another's (`SEC-8`).
"""

from collections import defaultdict

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import GradeBoundary, Subject

# Published standard boundaries per grade scale, highest grade first.
#
# These are the values a tutor starts from, not values the product asserts are
# correct for a given paper: real boundaries move every series, which is exactly
# why the editor exists. The alternative — an empty table in front of a stranger
# on day one — puts a data-entry wall between a new tutor and every number in
# the product (spec §7.1).
DEFAULT_BOUNDARIES: dict[str, list[dict]] = {
    "9-1": [
        {"grade": "9", "min": 90.0},
        {"grade": "8", "min": 80.0},
        {"grade": "7", "min": 70.0},
        {"grade": "6", "min": 62.0},
        {"grade": "5", "min": 54.0},
        {"grade": "4", "min": 46.0},
        {"grade": "3", "min": 36.0},
        {"grade": "2", "min": 26.0},
        {"grade": "1", "min": 16.0},
        {"grade": "U", "min": 0.0},
    ],
    "A*-E": [
        {"grade": "A*", "min": 90.0},
        {"grade": "A", "min": 80.0},
        {"grade": "B", "min": 70.0},
        {"grade": "C", "min": 60.0},
        {"grade": "D", "min": 50.0},
        {"grade": "E", "min": 40.0},
        {"grade": "U", "min": 0.0},
    ],
}


def defaults_for_scale(grade_scale: str) -> list[dict]:
    """A starting point for a scale, or an empty list for one we do not publish.

    Empty rather than a guess: a scale nobody wrote defaults for gets "no grade
    boundaries set" and the control that fixes it, which is honest. Inventing a
    ten-band split for an unknown scale would produce grades nothing stands
    behind (PROD-1).
    """
    return [dict(band) for band in DEFAULT_BOUNDARIES.get(grade_scale, [])]


async def resolve_grade_boundaries(
    session: AsyncSession, organization_id: int, subject: Subject
) -> list[dict]:
    """This organization's boundaries for the subject, highest grade first.

    An empty list means nothing is set, and every caller must render that as
    absent rather than mapping a score through it — `predict_grade` returns "—"
    and `grade_band` returns `None` for exactly this case.

    Every read path shares this one list, which is what makes a predicted grade
    and an averaging grade comparable: nothing constrains one list's grade labels
    to match another's, so [9, 7, 4, U] puts "4" at index 2 where a ten-grade
    list puts it at index 5. Reading a different list is a different band, not a
    rounding difference.
    """
    rows = (
        await session.scalars(
            select(GradeBoundary).where(
                GradeBoundary.organization_id == organization_id,
                GradeBoundary.subject_id == subject.id,
            )
        )
    ).all()
    return _as_bands(rows)


def _as_bands(rows) -> list[dict]:
    """Boundary rows as the ordered {grade, min} list every consumer expects.

    Sorted here rather than in the query: `predict_grade` walks the list top to
    bottom and returns the first grade the score meets, so an unordered list
    does not fail — it returns the wrong grade.
    """
    return [
        {"grade": b.grade_label, "min": b.min_percentage}
        for b in sorted(rows, key=lambda b: b.min_percentage, reverse=True)
    ]


async def org_boundaries(session: AsyncSession, organization_id: int) -> dict[int, list[dict]]:
    """Every boundary this organization has set, keyed by subject, in one query.

    The aggregate surfaces (today, the v1 summary, reports) walk several subjects
    at once; calling `resolve_grade_boundaries` per subject would reintroduce the
    per-row round trip those aggregates exist to remove.
    """
    by_subject: dict[int, list] = defaultdict(list)
    for row in (
        await session.scalars(
            select(GradeBoundary).where(GradeBoundary.organization_id == organization_id)
        )
    ).all():
        by_subject[row.subject_id].append(row)
    return {subject_id: _as_bands(rows) for subject_id, rows in by_subject.items()}


def boundaries_for(by_subject: dict[int, list[dict]], subject: Subject | None) -> list[dict]:
    """One subject's bands out of an `org_boundaries()` map — empty if unset."""
    if subject is None:
        return []
    return by_subject.get(subject.id, [])


async def set_org_boundaries(
    session: AsyncSession, organization_id: int, subject_id: int, bands: list[dict]
) -> None:
    """Replace this organization's boundaries for one subject.

    Replace, not merge: the editor submits the whole ordered list, and merging
    would leave a band the tutor deleted still in force with nothing on screen
    to show it. Scoped to one (organization, subject) pair, so one tenant's edit
    cannot touch another's rows — the reason this table exists.
    """
    await session.execute(
        delete(GradeBoundary).where(
            GradeBoundary.organization_id == organization_id,
            GradeBoundary.subject_id == subject_id,
        )
    )
    for band in bands:
        session.add(
            GradeBoundary(
                organization_id=organization_id,
                subject_id=subject_id,
                grade_label=band["grade"],
                min_percentage=float(band["min"]),
            )
        )
    await session.flush()
