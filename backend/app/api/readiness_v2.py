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
from app.services.grade_boundaries import boundaries_for, org_boundaries

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
    db: AsyncSession,
    snapshot: ReadinessSnapshot,
    subject: Subject,
    boundaries: list[dict],
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
        # The stored grade is shown only while the organization still has
        # boundaries to stand behind it. Clearing them leaves nothing for the
        # grade to have been mapped through, and a grade no current numbers
        # support is exactly what `PROD-2` forbids — `AV-11` made that table the
        # only source in task 2.4, and this surface was missed then.
        #
        # The snapshot itself is untouched: it is the honest record of what the
        # engine said at synthesis time, and the grade reappears if boundaries
        # are set again. `services/readiness_summary_v2.py` does the same thing
        # for `/readiness/*`, which is the surface the product actually serves.
        predicted_grade=snapshot.predicted_grade if boundaries else None,
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
    # One query for every subject below, rather than one per snapshot.
    #
    # Keyed on the **student's** organization, which is the one the grade was
    # mapped through: `readiness_v2_ai` synthesises it with
    # `resolve_grade_boundaries(session, student.organization_id, subject)` and
    # `readiness_summary_v2` reads it back the same way. A student may be
    # enrolled in a subject owned by a second organization (`visible_subject_ids`
    # scopes by enrolment, not tenancy), and keying on the *subject's* owner
    # would then validate the grade against a list it was never mapped through —
    # showing a "7" that the boundaries on screen do not produce (cubic proposed
    # exactly that).
    #
    # Which organization's boundaries should apply to a student taught by two is
    # a real product question, and an open one. It is not answered here, and
    # answering it means changing synthesis first.
    all_boundaries = await org_boundaries(db, student.organization_id)
    subjects_out = []
    for subject_id in subject_ids or []:
        subject = await db.get(Subject, subject_id)
        if subject is None:
            continue
        snapshot = await _latest_snapshot(db, student_id, subject_id)
        if snapshot is None:
            continue
        subjects_out.append(
            await _snapshot_out(db, snapshot, subject, boundaries_for(all_boundaries, subject))
        )
    return StudentReadinessV2Summary(
        student_id=student.id, student_name=student.name, subjects=subjects_out
    )
