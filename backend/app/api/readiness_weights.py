"""Tutor control over how the Readiness Engine weighs its seven factors.

Supersedes the v1 per-evidence-source sliders (api/preferences.py). Weights are
per organization, and saving them recomputes every student the tutor teaches —
otherwise the sliders would appear to do nothing until the next piece of
evidence arrived.
"""

from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import DbSession, TutorUser
from app.models import Group, GroupMember, ReadinessWeights
from app.schemas.readiness import ReadinessWeightsOut, ReadinessWeightsUpdate
from app.services.readiness_v2_ai import enqueue_readiness_v2_debounced

router = APIRouter(prefix="/readiness", tags=["readiness"])

WEIGHT_FIELDS = (
    "weight_topic_mastery",
    "weight_past_paper_performance",
    "weight_homework_performance",
    "weight_assessment_performance",
    "weight_syllabus_coverage",
    "weight_mistake_analysis",
    "weight_consistency",
    "half_life_days",
)


def _out(weights: ReadinessWeights | None) -> ReadinessWeightsOut:
    if weights is None:
        # Never persisted: report the model defaults rather than inventing a row.
        return ReadinessWeightsOut(
            **{f: getattr(ReadinessWeights.__table__.c, f).default.arg for f in WEIGHT_FIELDS}
        )
    return ReadinessWeightsOut(**{f: getattr(weights, f) for f in WEIGHT_FIELDS})


@router.get("/weights", response_model=ReadinessWeightsOut)
async def get_weights(db: DbSession, user: TutorUser) -> ReadinessWeightsOut:
    weights = await db.scalar(
        select(ReadinessWeights).where(ReadinessWeights.organization_id == user.organization_id)
    )
    return _out(weights)


@router.put("/weights", response_model=ReadinessWeightsOut)
async def update_weights(
    body: ReadinessWeightsUpdate, db: DbSession, user: TutorUser
) -> ReadinessWeightsOut:
    weights = await db.scalar(
        select(ReadinessWeights).where(ReadinessWeights.organization_id == user.organization_id)
    )
    if weights is None:
        weights = ReadinessWeights(organization_id=user.organization_id, tutor_id=user.id)
        db.add(weights)
    for field in WEIGHT_FIELDS:
        setattr(weights, field, getattr(body, field))

    # New weights change every score, so recompute the tutor's students. The
    # debounce means saving the sliders a few times in a row still costs one
    # run per student.
    students = (
        await db.scalars(
            select(GroupMember.student_id)
            .join(Group, Group.id == GroupMember.group_id)
            .where(Group.tutor_id == user.id)
            .distinct()
        )
    ).all()
    for student_id in students:
        await enqueue_readiness_v2_debounced(db, student_id, None)

    await db.commit()
    return _out(weights)
