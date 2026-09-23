"""Builds a per-subject readiness summary (overall score, predicted grade, weak
topics) for a student. Shared by the readiness API and the Student CRM
aggregation so both read the same numbers."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    ReadinessConfidence,
    ReadinessHistory,
    Subject,
    Topic,
    TopicReadiness,
    User,
)
from app.schemas.readiness import (
    StudentReadinessSummary,
    SubjectReadiness,
    TopicReadinessOut,
    WeakTopic,
)
from app.services.averaging import subject_averaging
from app.services.grade_boundaries import boundaries_for, org_boundaries
from app.services.grades import grade_band, predict_grade
from app.services.readiness_shared import (
    DIRECTION_NOISE_BAND,  # noqa: F401 - re-exported until 5.3b
    MONTH_WINDOW_DAYS,  # noqa: F401 - re-exported until 5.3b
    WEAK_THRESHOLD,
    ScorePoint,
    _aware,  # noqa: F401 - re-exported until 5.3b
    month_delta,
    period_delta,  # noqa: F401 - re-exported until 5.3b
    scores_of,
    trend_direction,
    v2_score_points,  # noqa: F401 - re-exported until 5.3b
    window_start,  # noqa: F401 - re-exported until 5.3b
)

# Evidence at this confidence or better counts as real for v1: whether a topic
# is weak enough to surface, and whether a student counts as covered by their
# class's readiness picture (services/groups.py imports this for the latter).
# v1-local because it is built on ReadinessConfidence, the enum 5.3b deletes
# with models/readiness.py; readiness_shared.CONFIDENT is the v2 replacement.
MIN_WEAK_CONFIDENCE = frozenset({ReadinessConfidence.medium, ReadinessConfidence.high})
CONFIDENT = MIN_WEAK_CONFIDENCE


# Each engine reads its own history, deliberately. A direction must describe
# the score it is shown beside: pairing a v1 score with an arrow derived from v2
# snapshots would let a stale 45 sit next to an arrow computed from a series
# that ran 40 -> 85 (PROD-1). Together these also reproduce what the trend
# endpoint draws — it prefers v2 and falls back to v1, and each engine here
# calls the matching one — so the arrow and the line stay the same claim.


async def v1_score_points(db: AsyncSession, student_id: int, subject_id: int) -> list[ScorePoint]:
    """Ordered (oldest-first) v1 history points — what build_summary reports."""
    return [
        (at, score)
        for at, score in (
            await db.execute(
                select(ReadinessHistory.recorded_at, ReadinessHistory.score)
                .where(
                    ReadinessHistory.student_id == student_id,
                    ReadinessHistory.subject_id == subject_id,
                )
                .order_by(ReadinessHistory.recorded_at)
            )
        ).all()
    ]


async def build_summary(
    db: AsyncSession, student: User, subject_ids: list[int]
) -> StudentReadinessSummary:
    subjects_out: list[SubjectReadiness] = []
    # One query covering every subject below, rather than one per subject in the
    # loop. Since task 2.4 this is the only source of a predicted grade: a
    # subject the organization has set no boundaries for gets no grade and no
    # band, never one mapped through numbers nobody entered (AV-11, PROD-2).
    all_boundaries = await org_boundaries(db, student.organization_id)
    for subject_id in subject_ids:
        subject = await db.get(Subject, subject_id)
        if subject is None:
            continue
        topics = (await db.scalars(select(Topic).where(Topic.subject_id == subject_id))).all()
        topic_by_id = {t.id: t for t in topics}
        readiness_rows = (
            await db.scalars(
                select(TopicReadiness).where(
                    TopicReadiness.student_id == student.id,
                    TopicReadiness.topic_id.in_(list(topic_by_id.keys()) or [0]),
                )
            )
        ).all()

        topic_out: list[TopicReadinessOut] = []
        weighted_sum = 0.0
        weight_total = 0.0
        weak: list[WeakTopic] = []
        for r in readiness_rows:
            topic = topic_by_id.get(r.topic_id)
            if topic is None:
                continue
            topic_out.append(
                TopicReadinessOut(
                    topic_id=topic.id,
                    topic_code=topic.code,
                    topic_title=topic.title,
                    score=r.score,
                    confidence=r.confidence.value,
                    evidence_count=r.evidence_count,
                )
            )
            weighted_sum += topic.weight * r.score
            weight_total += topic.weight
            if r.score <= WEAK_THRESHOLD and r.confidence in MIN_WEAK_CONFIDENCE:
                weak.append(
                    WeakTopic(
                        topic_id=topic.id,
                        topic_code=topic.code,
                        topic_title=topic.title,
                        score=r.score,
                    )
                )

        overall = round(weighted_sum / weight_total, 1) if weight_total > 0 else None
        boundaries = boundaries_for(all_boundaries, subject)
        grade = predict_grade(overall, boundaries) if overall is not None and boundaries else None
        status = grade_band(grade, boundaries)
        # Same boundary list as the predicted grade above, so the two grades are
        # comparable — which is the only reason showing both is useful (§3.3).
        averaging = await subject_averaging(db, student.id, subject_id)
        averaging_grade = (
            predict_grade(averaging.score, boundaries)
            if averaging.score is not None and boundaries
            else None
        )
        # No score means no arrow: a direction beside "not enough data yet"
        # would describe a value the card is not showing (PROD-2). The month's
        # movement comes from the same points as the arrow, so the two can never
        # contradict each other on screen.
        points = await v1_score_points(db, student.id, subject_id) if overall is not None else []
        direction = trend_direction(scores_of(points)) if overall is not None else None
        delta = month_delta(points) if overall is not None else None
        # How much of the subject this score actually speaks for. A score drawn
        # from 3 of 40 topics and one drawn from 40 of 40 are different claims
        # and must not render alike (PROD-2), so the counts travel with it.
        topics_with_evidence = sum(1 for t in topic_out if t.evidence_count > 0)
        topic_out.sort(key=lambda t: t.topic_code)
        weak.sort(key=lambda w: w.score)
        subjects_out.append(
            SubjectReadiness(
                subject_id=subject.id,
                subject_name=subject.name,
                exam_board=subject.exam_board,
                grade_scale=subject.grade_scale,
                score=overall,
                predicted_grade=grade,
                status=status,
                averaging_score=averaging.score,
                averaging_grade=averaging_grade,
                marked_piece_count=averaging.marked_piece_count,
                direction=direction,
                month_delta=delta,
                topics_with_evidence=topics_with_evidence,
                topic_count=len(topics),
                topics=topic_out,
                weak_topics=weak[:5],
            )
        )
    return StudentReadinessSummary(
        student_id=student.id, student_name=student.name, subjects=subjects_out
    )
