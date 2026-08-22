"""Read-only view of Readiness Engine v2's shadow-computed snapshots. Only
ever reads the latest already-computed ReadinessSnapshot per subject — never
triggers a computation itself, per the "idempotent reads" rule; v2 only
ever runs from the compute_readiness_v2 background job.

Kept separate from api/readiness.py (v1, still what the product actually
serves) so this stays a pure validation/comparison surface until the v2
cutover is decided — see docs/avora-architecture.md."""

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, DbSession
from app.api.readiness import visible_subject_ids
from app.models import FactorEvaluation, ReadinessSnapshot, Subject, Topic, User, UserRole
from app.schemas.readiness_v2 import (
    FactorEvaluationOut,
    ReadinessSnapshotOut,
    StudentReadinessV2Summary,
    WeakTopicOut,
)

router = APIRouter(prefix="/readiness/v2", tags=["readiness-v2"])


async def _latest_snapshot(
    db: AsyncSession, student_id: int, subject_id: int
) -> ReadinessSnapshot | None:
    return await db.scalar(
        select(ReadinessSnapshot)
        .where(
            ReadinessSnapshot.student_id == student_id, ReadinessSnapshot.subject_id == subject_id
        )
        .order_by(ReadinessSnapshot.created_at.desc())
        .limit(1)
    )


async def _snapshot_out(
    db: AsyncSession, snapshot: ReadinessSnapshot, subject: Subject
) -> ReadinessSnapshotOut:
    factor_rows = (
        await db.scalars(
            select(FactorEvaluation).where(
                FactorEvaluation.evaluation_run_id == snapshot.evaluation_run_id
            )
        )
    ).all()
    topic_ids = {r.topic_id for r in factor_rows if r.topic_id is not None}
    topics_by_id = {}
    if topic_ids:
        topics_by_id = {
            t.id: t for t in (await db.scalars(select(Topic).where(Topic.id.in_(topic_ids)))).all()
        }
    return ReadinessSnapshotOut(
        subject_id=subject.id,
        subject_name=subject.name,
        status=snapshot.status.value,
        score=snapshot.score,
        predicted_grade=snapshot.predicted_grade,
        weak_topics=[WeakTopicOut(**w) for w in snapshot.weak_topics],
        rationale=snapshot.rationale,
        recommended_revision=snapshot.recommended_revision,
        error=snapshot.error,
        created_at=snapshot.created_at,
        factors=[
            FactorEvaluationOut(
                factor=r.factor.value,
                topic_id=r.topic_id,
                topic_title=topics_by_id[r.topic_id].title if r.topic_id in topics_by_id else None,
                score=r.score,
                confidence=r.confidence.value,
                evidence_count=r.evidence_count,
                detail=r.detail,
            )
            for r in factor_rows
        ],
    )


@router.get("/students/{student_id}", response_model=StudentReadinessV2Summary)
async def student_readiness_v2(
    student_id: int, db: DbSession, user: CurrentUser
) -> StudentReadinessV2Summary:
    student = await db.get(User, student_id)
    if student is None or student.role != UserRole.student:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Student not found")
    subject_ids = await visible_subject_ids(db, user, student_id)
    subjects_out = []
    for subject_id in subject_ids or []:
        subject = await db.get(Subject, subject_id)
        if subject is None:
            continue
        snapshot = await _latest_snapshot(db, student_id, subject_id)
        if snapshot is None:
            continue
        subjects_out.append(await _snapshot_out(db, snapshot, subject))
    return StudentReadinessV2Summary(
        student_id=student.id, student_name=student.name, subjects=subjects_out
    )
