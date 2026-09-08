"""Read and set an organization's grade boundaries for a subject.

This is the control the "Set them →" link on every absent-band surface points
at. Until it existed, `services/grades.py` returned "—" for a subject with no
boundaries and there was nothing a tutor could do about it.

The org-scoped `GradeBoundary` table is the **only** source since task 2.4
(`AV-11`); `Subject.grade_boundaries` is gone. A subject this organization has
not set has no predicted grade anywhere in the product — never one mapped
through numbers nobody entered (`PROD-2`).

The organization comes from the authenticated tutor and never from the path
(PROD-4 / SEC-7); the role gate is a signature dependency (SEC-11 / BE-17).
"""

from fastapi import APIRouter

from app.api.deps import CurrentUser, DbSession, TutorUser, owned_subject, visible_subject
from app.schemas.grade_boundaries import GradeBoundariesIn, GradeBoundariesOut
from app.services.grade_boundaries import (
    defaults_for_scale,
    resolve_grade_boundaries,
    set_org_boundaries,
)

router = APIRouter(prefix="/subjects", tags=["grade-boundaries"])


@router.get("/{subject_id}/grade-boundaries", response_model=GradeBoundariesOut)
async def read_grade_boundaries(
    subject_id: int, db: DbSession, user: CurrentUser
) -> GradeBoundariesOut:
    """What this organization's grades are mapped through, and whether it is set.

    `source` travels with the list because the two cases are different facts and
    must not render alike: the tutor's own numbers, and a published starting
    point nobody has confirmed. `PROD-8` requires the second to be labelled as
    unconfirmed wherever it is shown.
    """
    # Every role reaches this route, so visibility is by enrolment rather than
    # by organization: a student must not read boundaries for a subject they are
    # not taught, and must not be refused one they are (SEC-8).
    subject = await visible_subject(db, subject_id, user)
    boundaries = await resolve_grade_boundaries(db, user.organization_id, subject)
    if boundaries:
        # One source since 2.4, so a non-empty list is the organization's own —
        # there is no other list it could have come from.
        return GradeBoundariesOut(
            subject_id=subject.id,
            subject_name=subject.name,
            grade_scale=subject.grade_scale,
            source="organization",
            boundaries=boundaries,
        )
    # Nothing set: hand back the published starting point for this scale so the
    # editor opens pre-filled rather than blank, clearly marked as not yet
    # confirmed. Offered, not written — until the tutor saves, this subject has
    # no predicted grade anywhere in the product.
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
    subject = await owned_subject(db, subject_id, user)
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
