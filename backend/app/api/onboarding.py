"""Onboarding state and acknowledgements (task 9.1a).

The backend decides what is complete; no frontend gate is the control (`SEC-10`).
"""

from fastapi import APIRouter, HTTPException, status

from app.api.deps import DbSession, TutorUser
from app.schemas.onboarding import AcknowledgementIn, OnboardingState
from app.services.onboarding import (
    AcknowledgementError,
    SubjectNotFound,
    acknowledge,
    load_state,
)

router = APIRouter(prefix="/onboarding", tags=["onboarding"])


@router.get("", response_model=OnboardingState)
async def get_onboarding(db: DbSession, user: TutorUser) -> OnboardingState:
    return await load_state(db, user)


@router.post("/acknowledgements", response_model=OnboardingState)
async def post_acknowledgement(
    body: AcknowledgementIn, db: DbSession, user: TutorUser
) -> OnboardingState:
    try:
        await acknowledge(db, user, body.item, body.subject_id)
    except AcknowledgementError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    except SubjectNotFound:
        # 404, not 403: integer keys are enumerable (`API-7`, `SEC-9`).
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Subject not found") from None
    await db.commit()
    return await load_state(db, user)
