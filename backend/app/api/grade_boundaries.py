"""Read and set an organization's grade boundaries for a subject.

This is the control the "Set them →" link on every absent-band surface points
at. Until it existed, `services/grades.py` returned "—" for a subject with no
boundaries and there was nothing a tutor could do about it.

**The write target is the org-scoped `GradeBoundary` table, never
`Subject.grade_boundaries`.** `Subject` has no `organization_id`, so a write
there would change every other organization's predicted grades (SEC-8). There is
no endpoint in this file, or anywhere else, that can reach that column.

The organization comes from the authenticated tutor and never from the path
(PROD-4 / SEC-7); the role gate is a signature dependency (SEC-11 / BE-17).
"""

from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentUser, DbSession, TutorUser
from app.models import Subject
from app.schemas.grade_boundaries import GradeBoundariesIn, GradeBoundariesOut
from app.services.grade_boundaries import (
    defaults_for_scale,
    has_org_boundaries,
    resolve_grade_boundaries,
    set_org_boundaries,
)

router = APIRouter(prefix="/subjects", tags=["grade-boundaries"])


async def _subject(db, subject_id: int) -> Subject:
    subject = await db.get(Subject, subject_id)
    if subject is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Subject not found")
    return subject


@router.get("/{subject_id}/grade-boundaries", response_model=GradeBoundariesOut)
async def read_grade_boundaries(
    subject_id: int, db: DbSession, user: CurrentUser
) -> GradeBoundariesOut:
    """What this organization's grades are currently mapped through, and where
    that list came from.

    `source` travels with the list because the three cases are different facts
    and must not render alike: a tutor's own numbers, a published default nobody
    has confirmed, and nothing at all. PROD-8 requires the middle one to be
    labelled as unconfirmed wherever it is shown.
    """
    subject = await _subject(db, subject_id)
    boundaries = await resolve_grade_boundaries(db, user.organization_id, subject)
    if boundaries:
        # Ask directly whether the org set its own values rather than inferring
        # it from the resolved list's object identity, which would break the
        # moment resolve_grade_boundaries copied the subject's list (Qodo).
        source = (
            "organization"
            if await has_org_boundaries(db, user.organization_id, subject.id)
            else "subject"
        )
        return GradeBoundariesOut(
            subject_id=subject.id,
            subject_name=subject.name,
            grade_scale=subject.grade_scale,
            source=source,
            boundaries=boundaries,
        )
    # Nothing set anywhere: hand back the published starting point for this
    # scale so the editor opens pre-filled rather than blank, clearly marked as
    # not yet confirmed. Offered, not written — a tutor who deliberately left
    # this empty must not find it filled in on their behalf.
    return GradeBoundariesOut(
        subject_id=subject.id,
        subject_name=subject.name,
        grade_scale=subject.grade_scale,
        source="none",
        boundaries=defaults_for_scale(subject.grade_scale),
    )


@router.put("/{subject_id}/grade-boundaries", response_model=GradeBoundariesOut)
async def write_grade_boundaries(
    subject_id: int, body: GradeBoundariesIn, db: DbSession, user: TutorUser
) -> GradeBoundariesOut:
    """Set this organization's boundaries for one subject.

    Nothing recomputes here. Predicted grades are mapped at read time through
    whatever this returns, so the change is live on the next page load without a
    job — and the stored snapshots keep the grade they were synthesized with
    until they are next computed, which is the honest record of what the engine
    said at the time.
    """
    subject = await _subject(db, subject_id)
    await set_org_boundaries(
        db,
        user.organization_id,
        subject.id,
        [band.model_dump() for band in body.boundaries],
    )
    await db.commit()
    return GradeBoundariesOut(
        subject_id=subject.id,
        subject_name=subject.name,
        grade_scale=subject.grade_scale,
        source="organization",
        boundaries=[band.model_dump() for band in body.boundaries],
    )
