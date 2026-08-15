"""Where a subject's grade boundaries come from, and in what order.

Two sources exist and always have: the global `Subject.grade_boundaries`, shared
by every organization, and the org-scoped `GradeBoundary` table. Until now
nothing wrote the second one, so the precedence documented on the model was a
claim about a code path that could not be exercised. This module is the one
place that resolves them, and the one place that writes the override.

**The write target is `GradeBoundary`, never `Subject`.** `Subject` carries no
`organization_id` (models/syllabus.py) — every tenant teaches the same Chemistry
row. A tutor-gated write to `Subject.grade_boundaries` would therefore move every
other organization's predicted grades, which is the precise failure SEC-8 exists
to prevent. There is deliberately no endpoint that can reach that column.

**Defaults are offered, never backfilled.** A tutor who deliberately left
boundaries empty must not find them filled in, so nothing here writes to a
subject that already has an answer, and `defaults_for_scale` is a suggestion the
editor pre-fills rather than a value written on their behalf (PROD-8: an
unconfirmed default is labelled as one).
"""

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
    """The organization's override if it has one, the global default otherwise.

    This is *the* precedence rule, and it is now true rather than descriptive:
    with a writer for `GradeBoundary` it is reachable, and
    `test_org_override_takes_precedence_over_global_default` exercises it.

    Every read path shares it — readiness_v2_ai maps the predicted grade through
    this list at synthesis time, and readiness_summary_v2 bands that grade and
    maps the averaging grade through the same one. Nothing constrains an
    organization's grade_label set to match the subject's, so an org list of
    [9, 7, 4, U] puts "4" at index 2 where a ten-grade subject list puts it at
    index 5: reading the wrong list is a different band, not a rounding
    difference, and predicted-beside-averaging only means anything if both used
    the same list.
    """
    org_boundaries = (
        await session.scalars(
            select(GradeBoundary).where(
                GradeBoundary.organization_id == organization_id,
                GradeBoundary.subject_id == subject.id,
            )
        )
    ).all()
    if org_boundaries:
        ordered = sorted(org_boundaries, key=lambda b: b.min_percentage, reverse=True)
        return [{"grade": b.grade_label, "min": b.min_percentage} for b in ordered]
    return subject.grade_boundaries


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
