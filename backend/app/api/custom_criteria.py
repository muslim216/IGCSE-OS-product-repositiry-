"""Tutor-defined criteria (task 5.4b) — defining them.

Scoring a student lives beside the rest of the CRM in `api/students.py`. The
organization comes from the authenticated tutor, never the path (`SEC-7`);
another organization's criterion or subject is a 404, never a 403 (`API-7`).
No hard delete: a criterion with scores is archived, so its scores and their
audit trail keep something to point at.
"""

from fastapi import APIRouter, HTTPException, status

from app.api.deps import DbSession, TutorUser, owned_subject
from app.models import CustomCriterion
from app.schemas.custom_criteria import (
    CustomCriterionCreate,
    CustomCriterionOut,
    CustomCriterionUpdate,
)
from app.services.custom_criteria import (
    CriterionNotFound,
    create_criterion,
    list_criteria,
    owned_criterion,
    update_criterion,
)

router = APIRouter(prefix="/custom-criteria", tags=["custom-criteria"])


def _out(criterion: CustomCriterion) -> CustomCriterionOut:
    return CustomCriterionOut(
        id=criterion.id,
        name=criterion.name,
        description=criterion.description,
        subject_id=criterion.subject_id,
        archived_at=criterion.archived_at,
        created_by_id=criterion.created_by_id,
        created_at=criterion.created_at,
    )


@router.get("", response_model=list[CustomCriterionOut])
async def read_criteria(
    db: DbSession, user: TutorUser, include_archived: bool = False
) -> list[CustomCriterionOut]:
    rows = await list_criteria(db, user.organization_id, include_archived=include_archived)
    return [_out(row) for row in rows]


@router.post("", response_model=CustomCriterionOut, status_code=status.HTTP_201_CREATED)
async def add_criterion(
    body: CustomCriterionCreate, db: DbSession, user: TutorUser
) -> CustomCriterionOut:
    if body.subject_id is not None:
        await owned_subject(db, body.subject_id, user)
    criterion = await create_criterion(
        db,
        user.organization_id,
        user.id,
        name=body.name,
        description=body.description,
        subject_id=body.subject_id,
    )
    await db.commit()
    return _out(criterion)


@router.patch("/{criterion_id}", response_model=CustomCriterionOut)
async def edit_criterion(
    criterion_id: int, body: CustomCriterionUpdate, db: DbSession, user: TutorUser
) -> CustomCriterionOut:
    try:
        criterion = await owned_criterion(db, user.organization_id, criterion_id)
    except CriterionNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Criterion not found") from exc
    update_criterion(criterion, body.model_dump(exclude_unset=True))
    await db.commit()
    return _out(criterion)
