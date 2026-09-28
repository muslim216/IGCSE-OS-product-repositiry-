"""Tutor control over how the Readiness Engine weighs its six factors.

This replaced the v1 per-evidence-source sliders (deleted in 5.3b). Weights are
per organization, and saving them recomputes every student the tutor teaches —
otherwise the sliders would appear to do nothing until the next piece of
evidence arrived.

Since task 5.4a a subject may carry its own override row, which replaces the
account row whole (decision 8) — the precedence lives in
services/readiness_config.py, not here. `?subject_id=` picks the scope; no
parameter is the account row.
"""

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import DbSession, TutorUser
from app.models import Group, GroupMember, ReadinessWeights, Subject, User
from app.schemas.readiness import ReadinessWeightsOut, ReadinessWeightsUpdate
from app.services.readiness_config import (
    FACTOR_WEIGHT_ATTR,
    enabled_attr,
    resolve_readiness_config,
)
from app.services.readiness_v2_ai import enqueue_readiness_v2_debounced

router = APIRouter(prefix="/readiness", tags=["readiness"])

WRITABLE_FIELDS = (
    *FACTOR_WEIGHT_ATTR.values(),
    *(enabled_attr(f) for f in FACTOR_WEIGHT_ATTR),
    "half_life_days",
)


async def _check_subject(db: AsyncSession, user: User, subject_id: int | None) -> None:
    """404, never 403: another tenant's subject id must be indistinguishable
    from one that does not exist (API-7, SEC-7)."""
    if subject_id is None:
        return
    owned = await db.scalar(
        select(Subject.id).where(
            Subject.id == subject_id, Subject.organization_id == user.organization_id
        )
    )
    if owned is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Subject not found")


async def _scope_row(
    db: AsyncSession, user: User, subject_id: int | None
) -> ReadinessWeights | None:
    """The row stored for exactly this scope — no fallback, unlike the resolver."""
    return await db.scalar(
        select(ReadinessWeights).where(
            ReadinessWeights.organization_id == user.organization_id,
            ReadinessWeights.subject_id.is_(None)
            if subject_id is None
            else ReadinessWeights.subject_id == subject_id,
        )
    )


async def _out(db: AsyncSession, user: User, subject_id: int | None) -> ReadinessWeightsOut:
    config = await resolve_readiness_config(db, user.organization_id, subject_id)
    return ReadinessWeightsOut(
        **config.weights,
        **{enabled_attr(f): f in config.enabled for f in FACTOR_WEIGHT_ATTR},
        half_life_days=config.half_life_days,
        subject_id=subject_id,
        source=config.source,
    )


async def _recompute(db: AsyncSession, user: User, subject_id: int | None) -> None:
    """New weights change every score in scope, so recompute it. The debounce
    means saving the sliders a few times in a row still costs one run per
    (student, subject).

    The scope is the organization's, not the saving tutor's: the config is
    shared, so a colleague's students would otherwise keep a score built on
    the old one. Enrolment is by group, so a subject run only ever reaches a
    student who takes that subject. An account save skips subjects with their
    own override — the result cannot change, and each run is an AI call."""
    query = (
        select(GroupMember.student_id, Group.subject_id)
        .join(Group, Group.id == GroupMember.group_id)
        .where(Group.organization_id == user.organization_id)
        .distinct()
    )
    if subject_id is not None:
        query = query.where(Group.subject_id == subject_id)
    else:
        query = query.where(
            Group.subject_id.not_in(
                select(ReadinessWeights.subject_id).where(
                    ReadinessWeights.organization_id == user.organization_id,
                    ReadinessWeights.subject_id.is_not(None),
                )
            )
        )
    for student_id, group_subject_id in (await db.execute(query)).all():
        await enqueue_readiness_v2_debounced(db, student_id, group_subject_id)


@router.get("/weights", response_model=ReadinessWeightsOut)
async def get_weights(
    db: DbSession, user: TutorUser, subject_id: int | None = None
) -> ReadinessWeightsOut:
    await _check_subject(db, user, subject_id)
    return await _out(db, user, subject_id)


@router.put("/weights", response_model=ReadinessWeightsOut)
async def update_weights(
    body: ReadinessWeightsUpdate, db: DbSession, user: TutorUser, subject_id: int | None = None
) -> ReadinessWeightsOut:
    await _check_subject(db, user, subject_id)
    weights = await _scope_row(db, user, subject_id)
    if weights is None:
        weights = ReadinessWeights(
            organization_id=user.organization_id, subject_id=subject_id, tutor_id=user.id
        )
        db.add(weights)
    for field in WRITABLE_FIELDS:
        setattr(weights, field, getattr(body, field))
    await _recompute(db, user, subject_id)
    await db.commit()
    return await _out(db, user, subject_id)


@router.delete("/weights", status_code=status.HTTP_204_NO_CONTENT)
async def delete_subject_override(db: DbSession, user: TutorUser, subject_id: int) -> None:
    """Remove a subject's override, so it falls back to the account row.
    `subject_id` is required: the account row is not an override and has
    nothing to fall back to."""
    await _check_subject(db, user, subject_id)
    weights = await _scope_row(db, user, subject_id)
    if weights is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No override for this subject")
    await db.delete(weights)
    await _recompute(db, user, subject_id)
    await db.commit()
