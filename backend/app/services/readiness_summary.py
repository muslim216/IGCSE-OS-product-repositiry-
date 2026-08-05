"""Builds a per-subject readiness summary (overall score, predicted grade, weak
topics) for a student. Shared by the readiness API and the Student CRM
aggregation so both read the same numbers."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ReadinessConfidence, Subject, Topic, TopicReadiness, User
from app.schemas.readiness import (
    StudentReadinessSummary,
    SubjectReadiness,
    TopicReadinessOut,
    WeakTopic,
)
from app.services.grades import predict_grade

# Topics at or below this score (with enough confidence) are surfaced as weak.
WEAK_THRESHOLD = 60.0
MIN_WEAK_CONFIDENCE = {ReadinessConfidence.medium, ReadinessConfidence.high}


async def build_summary(
    db: AsyncSession, student: User, subject_ids: list[int]
) -> StudentReadinessSummary:
    subjects_out: list[SubjectReadiness] = []
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
        grade = predict_grade(overall, subject.grade_boundaries) if overall is not None else None
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
                topics=topic_out,
                weak_topics=weak[:5],
            )
        )
    return StudentReadinessSummary(
        student_id=student.id, student_name=student.name, subjects=subjects_out
    )
