"""The Readiness Engine.

Deterministic and explainable — no ML. Every topic score is a weighted average
of evidence, where each piece is weighted by:
  - its source (mocks count most, then homework, quizzes, observations), and
  - exponential time decay (recent evidence dominates; half-life ~45 days).

Confidence reflects how much recent evidence backs a score. Low-confidence
topics are shown as "not enough data yet", never as a false-precise number.

The scoring functions are pure (operate on plain dataclasses) so they can be
unit-tested without a database. recompute_student() is the DB-facing entry
point run from the job worker after marks are finalized or observations added.
"""

import math
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Evidence,
    EvidenceSource,
    ReadinessConfidence,
    ReadinessHistory,
    Subject,
    Topic,
    TopicReadiness,
)

# Half-life of evidence relevance, in days.
HALF_LIFE_DAYS = 45.0

SOURCE_WEIGHTS: dict[EvidenceSource, float] = {
    EvidenceSource.mock: 1.5,
    EvidenceSource.homework: 1.0,
    EvidenceSource.quiz: 0.8,
    EvidenceSource.observation: 0.5,
}


@dataclass(frozen=True)
class EvidencePoint:
    source: EvidenceSource
    score_pct: float
    occurred_at: datetime
    max_marks: int = 0


@dataclass(frozen=True)
class TopicResult:
    score: float
    confidence: ReadinessConfidence
    evidence_count: int


def _decay(age_days: float) -> float:
    return math.pow(0.5, age_days / HALF_LIFE_DAYS)


def _confidence(points: list[EvidencePoint], now: datetime) -> ReadinessConfidence:
    """Confidence grows with the amount of recent, decay-weighted evidence.

    The effective count sums each point's time-decay so stale evidence counts
    for less. Recent-count thresholds (recent = within one half-life) provide a
    floor so a single fresh mock still reads as at least 'low'.
    """
    if not points:
        return ReadinessConfidence.none
    effective = sum(_decay(_age_days(p.occurred_at, now)) for p in points)
    recent = sum(1 for p in points if _age_days(p.occurred_at, now) <= HALF_LIFE_DAYS)
    if recent >= 3 and effective >= 2.5:
        return ReadinessConfidence.high
    if recent >= 2 and effective >= 1.2:
        return ReadinessConfidence.medium
    return ReadinessConfidence.low


def _age_days(occurred_at: datetime, now: datetime) -> float:
    if occurred_at.tzinfo is None:
        occurred_at = occurred_at.replace(tzinfo=timezone.utc)
    return max(0.0, (now - occurred_at).total_seconds() / 86400.0)


def compute_topic(points: list[EvidencePoint], now: datetime | None = None) -> TopicResult:
    """Pure scoring for one topic from its evidence points."""
    now = now or datetime.now(timezone.utc)
    if not points:
        return TopicResult(score=0.0, confidence=ReadinessConfidence.none, evidence_count=0)
    total_weight = 0.0
    weighted_sum = 0.0
    for p in points:
        w = SOURCE_WEIGHTS[p.source] * _decay(_age_days(p.occurred_at, now))
        total_weight += w
        weighted_sum += w * p.score_pct
    score = weighted_sum / total_weight if total_weight > 0 else 0.0
    return TopicResult(
        score=round(score, 1),
        confidence=_confidence(points, now),
        evidence_count=len(points),
    )


def subject_readiness(
    topic_results: list[tuple[TopicResult, float]],
) -> float:
    """Topic-weight-weighted average of topic scores, counting only topics that
    have at least some evidence. Each item is (result, topic_weight)."""
    total_weight = 0.0
    weighted = 0.0
    for result, topic_weight in topic_results:
        if result.confidence == ReadinessConfidence.none:
            continue
        total_weight += topic_weight
        weighted += topic_weight * result.score
    if total_weight == 0:
        return 0.0
    return round(weighted / total_weight, 1)


async def recompute_student(session: AsyncSession, payload: dict) -> None:
    """Recompute topic readiness for one student (optionally scoped to a
    subject) and record a subject-readiness history snapshot."""
    student_id = payload["student_id"]
    subject_id = payload.get("subject_id")
    now = datetime.now(timezone.utc)

    subject_query = select(Subject)
    if subject_id is not None:
        subject_query = subject_query.where(Subject.id == subject_id)
    subjects = (await session.scalars(subject_query)).all()

    for subject in subjects:
        topics = (
            await session.scalars(select(Topic).where(Topic.subject_id == subject.id))
        ).all()
        topic_ids = [t.id for t in topics]
        if not topic_ids:
            continue

        evidence_rows = (
            await session.scalars(
                select(Evidence).where(
                    Evidence.student_id == student_id, Evidence.topic_id.in_(topic_ids)
                )
            )
        ).all()
        by_topic: dict[int, list[EvidencePoint]] = {}
        for e in evidence_rows:
            by_topic.setdefault(e.topic_id, []).append(
                EvidencePoint(
                    source=e.source_type,
                    score_pct=e.score_pct,
                    occurred_at=e.occurred_at,
                    max_marks=e.max_marks,
                )
            )

        existing = {
            tr.topic_id: tr
            for tr in (
                await session.scalars(
                    select(TopicReadiness).where(
                        TopicReadiness.student_id == student_id,
                        TopicReadiness.topic_id.in_(topic_ids),
                    )
                )
            ).all()
        }

        results: list[tuple[TopicResult, float]] = []
        has_any_evidence = False
        for topic in topics:
            points = by_topic.get(topic.id, [])
            result = compute_topic(points, now)
            results.append((result, topic.weight))
            if result.confidence != ReadinessConfidence.none:
                has_any_evidence = True
            row = existing.get(topic.id)
            if result.confidence == ReadinessConfidence.none:
                # No evidence: drop any stale snapshot, don't store a fake 0.
                if row is not None:
                    await session.delete(row)
                continue
            if row is None:
                row = TopicReadiness(student_id=student_id, topic_id=topic.id)
                session.add(row)
            row.score = result.score
            row.confidence = result.confidence
            row.evidence_count = result.evidence_count
            row.updated_at = now

        if has_any_evidence:
            overall = subject_readiness(results)
            session.add(
                ReadinessHistory(
                    student_id=student_id,
                    subject_id=subject.id,
                    score=overall,
                    recorded_at=now,
                )
            )
