"""Readiness Engine v2, Layer 1 — deterministic, explainable factor
sub-scores.

Pure functions over plain dataclasses (no DB session, no I/O). Each function
returns a FactorResult: a score (or None for "no data"), a confidence level,
an evidence count, and a JSON-safe detail dict — the same shape a
FactorEvaluation row stores.

Being pure and isolated means these unit-test without a database, and the
DB-facing gathering step (services/readiness_v2.py) is the only place that
queries anything — kept out of any HTTP request path and run only from the
compute_readiness_v2 background job.
"""

import math
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from app.models import FactorConfidence

# Half-life of evidence relevance, in days.
HALF_LIFE_DAYS = 45.0


def _decay(age_days: float, half_life: float = HALF_LIFE_DAYS) -> float:
    return math.pow(0.5, age_days / half_life)


def _age_days(occurred_at: datetime, now: datetime) -> float:
    if occurred_at.tzinfo is None:
        occurred_at = occurred_at.replace(tzinfo=timezone.utc)
    return max(0.0, (now - occurred_at).total_seconds() / 86400.0)


@dataclass(frozen=True)
class FactorResult:
    score: float | None
    confidence: FactorConfidence
    evidence_count: int
    detail: dict = field(default_factory=dict)


NO_DATA = FactorResult(score=None, confidence=FactorConfidence.no_data, evidence_count=0, detail={})


def _confidence_from_count(n: int, *, medium_at: int = 2, high_at: int = 4) -> FactorConfidence:
    if n <= 0:
        return FactorConfidence.no_data
    if n >= high_at:
        return FactorConfidence.high
    if n >= medium_at:
        return FactorConfidence.medium
    return FactorConfidence.low


# ---- 1. Topic Mastery ---------------------------------------------------

DIFFICULTY_WEIGHT = {"easy": 0.8, "medium": 1.0, "hard": 1.3, None: 1.0}


@dataclass(frozen=True)
class MarkedQuestion:
    """One marked question contributing to a topic's mastery."""

    difficulty: str | None  # "easy" | "medium" | "hard" | None (unrated)
    pct: float  # 0..100
    occurred_at: datetime


# A tutor's starting estimate, relative to a medium-difficulty marked question
# (1.0). The weight v1 gave the same source, carried over by decision 14: worth
# having — a class with nothing marked shows a new tutor nothing — and worth the
# least, because it is the only input that is not a mark on a piece of work
# (PROD-8).
TUTOR_ESTIMATE_WEIGHT = 0.4


@dataclass(frozen=True)
class TutorEstimate:
    """The tutor's self-declared starting score for one topic (Evidence with
    source_type=tutor_estimate)."""

    pct: float  # 0..100
    occurred_at: datetime


def topic_mastery(
    questions: list[MarkedQuestion],
    now: datetime | None = None,
    estimate: TutorEstimate | None = None,
) -> FactorResult:
    """Decay-weighted average across difficulty tiers — succeeding on harder
    questions counts for more, so familiarity with easy questions alone
    doesn't read as mastery.

    A tutor's estimate joins as a prior that gives way. Time decay alone would
    not do that: the half-life discounts an estimate and a mark equally, so on
    a quiet topic a September guess would keep its full relative weight into
    May. Dividing its weight by one more than the marked questions makes each
    mark push it further out of the answer; it is never deleted, because the
    row is the record of what the score was built from (PROD-1)."""
    if not questions and estimate is None:
        return NO_DATA
    now = now or datetime.now(timezone.utc)
    total_weight = 0.0
    weighted_sum = 0.0
    by_tier: dict[str, list[float]] = {}
    for q in questions:
        w = DIFFICULTY_WEIGHT.get(q.difficulty, 1.0) * _decay(_age_days(q.occurred_at, now))
        total_weight += w
        weighted_sum += w * q.pct
        by_tier.setdefault(q.difficulty or "unrated", []).append(q.pct)
    detail: dict = {
        "by_difficulty": {tier: round(sum(v) / len(v), 1) for tier, v in by_tier.items()}
    }
    if estimate is not None:
        w = (
            TUTOR_ESTIMATE_WEIGHT
            * _decay(_age_days(estimate.occurred_at, now))
            / (1 + len(questions))
        )
        total_weight += w
        weighted_sum += w * estimate.pct
        # The label every reader shows (PROD-8): how much of this score is the
        # tutor's own judgement rather than marked work.
        detail["tutor_estimate"] = {
            "pct": round(estimate.pct, 1),
            "share": round(w / total_weight, 2),
        }
    score = round(weighted_sum / total_weight, 1) if total_weight > 0 else None
    return FactorResult(
        score=score,
        # An estimate is never evidence of certainty: alone it is `low` (scored,
        # so the bar shows; below CONFIDENT, so it names no class weakness), and
        # beside marked work confidence comes from the marked work only.
        confidence=(_confidence_from_count(len(questions)) if questions else FactorConfidence.low),
        evidence_count=len(questions) + (1 if estimate is not None else 0),
        detail=detail,
    )


# ---- 2. Past Paper Performance ------------------------------------------


@dataclass(frozen=True)
class PastPaperAttemptPoint:
    pct: float
    timed: bool
    attempted_at: date


def past_paper_performance(attempts: list[PastPaperAttemptPoint]) -> FactorResult:
    if not attempts:
        return NO_DATA
    ordered = sorted(attempts, key=lambda a: a.attempted_at)
    avg = sum(a.pct for a in ordered) / len(ordered)
    timed_ratio = sum(1 for a in ordered if a.timed) / len(ordered)
    trend = None
    if len(ordered) >= 2:
        half = len(ordered) // 2
        first_half = sum(a.pct for a in ordered[:half]) / half
        second_half = sum(a.pct for a in ordered[half:]) / (len(ordered) - half)
        trend = round(second_half - first_half, 1)
    return FactorResult(
        score=round(avg, 1),
        confidence=_confidence_from_count(len(ordered)),
        evidence_count=len(ordered),
        detail={
            "trend": trend,
            "timed_ratio": round(timed_ratio, 2),
            "attempt_count": len(ordered),
        },
    )


# ---- 3. Homework Performance ---------------------------------------------


@dataclass(frozen=True)
class HomeworkPoint:
    submitted: bool  # handed in — whether or not marking has finished
    pct: float | None  # None until the submission is settled


def homework_performance(points: list[HomeworkPoint]) -> FactorResult:
    if not points:
        return NO_DATA
    # Narrowed once so `pct` is non-optional below — a second `is not None`
    # inside the average would divide a shrinking numerator by a fixed
    # denominator, silently scoring a missing measurement as 0 (PROD-2).
    marked = [p.pct for p in points if p.pct is not None]
    submitted_count = sum(1 for p in points if p.submitted)
    # Completion is a fact shown beside readiness, never inside the score
    # (AV-32): acing half the work and skipping the rest is reported as
    # exactly that, not blended into one number that hides which it was.
    detail = {
        "completion_rate": round(submitted_count / len(points), 2),
        "assignment_count": len(points),
        "submitted_count": submitted_count,
        "marked_count": len(marked),
        "accuracy": None,
    }
    if not marked:
        # Nothing marked yet means no accuracy exists — the factor is omitted,
        # not scored 0, while the completion fact above still stands.
        return FactorResult(
            score=None, confidence=FactorConfidence.no_data, evidence_count=0, detail=detail
        )
    accuracy = sum(marked) / len(marked)
    detail["accuracy"] = round(accuracy, 1)
    return FactorResult(
        score=round(accuracy, 1),
        confidence=_confidence_from_count(len(marked)),
        evidence_count=len(marked),
        detail=detail,
    )


# ---- 4. Assessment Performance --------------------------------------------


@dataclass(frozen=True)
class AssessmentPoint:
    pct: float
    occurred_at: datetime


def assessment_performance(
    points: list[AssessmentPoint], now: datetime | None = None
) -> FactorResult:
    if not points:
        return NO_DATA
    now = now or datetime.now(timezone.utc)
    total_weight = 0.0
    weighted_sum = 0.0
    for p in points:
        w = _decay(_age_days(p.occurred_at, now))
        total_weight += w
        weighted_sum += w * p.pct
    score = round(weighted_sum / total_weight, 1) if total_weight > 0 else None
    return FactorResult(
        score=score,
        confidence=_confidence_from_count(len(points)),
        evidence_count=len(points),
        detail={"assessment_count": len(points)},
    )


# ---- 5. Syllabus Coverage --------------------------------------------------


@dataclass(frozen=True)
class TopicCoverage:
    taught: bool
    practiced: bool  # has any evidence
    mastered: bool  # mastery score at/above the "mastered" threshold


def syllabus_coverage(topics: list[TopicCoverage]) -> FactorResult:
    if not topics:
        return NO_DATA
    taught = sum(1 for t in topics if t.taught)
    practiced = sum(1 for t in topics if t.taught and t.practiced)
    mastered = sum(1 for t in topics if t.taught and t.mastered)
    total = len(topics)
    # Being taught counts, practicing counts more, mastering most.
    score = (taught * 0.3 + practiced * 0.35 + mastered * 0.35) / total * 100
    return FactorResult(
        score=round(score, 1),
        confidence=_confidence_from_count(
            taught, medium_at=max(1, total // 3), high_at=max(1, (total * 2) // 3)
        ),
        evidence_count=taught,
        detail={
            "topics_total": total,
            "topics_taught": taught,
            "topics_practiced": practiced,
            "topics_mastered": mastered,
        },
    )


# ---- 6. Mistake Analysis ----------------------------------------------------


@dataclass(frozen=True)
class MistakePoint:
    category: str
    severity: int  # 1 (minor) .. 3 (major)
    occurred_at: datetime


def mistake_analysis(
    mistakes: list[MistakePoint], analysed_questions: int, now: datetime | None = None
) -> FactorResult:
    """Fewer, less severe, less-recent mistakes relative to the volume of work
    **examined for mistakes** -> a higher score.

    The denominator is analysed questions, not marked questions, and that
    distinction is the whole point. An empty mistakes table is indistinguishable
    from a flawless student, so counting every marked question here scored a
    confident 100.0 for everyone and fed it into a weighted factor (PROD-2).
    A question is only counted once something has actually looked at it —
    `submissions.mistakes_analysed_at`, set by the tag_mistakes job.

    analysed_questions=0 is "no data". Zero mistakes across analysed work is a
    clean record and scores 100.0, which is a measurement rather than a guess.
    """
    if analysed_questions <= 0:
        return NO_DATA
    now = now or datetime.now(timezone.utc)
    penalty = sum(m.severity * _decay(_age_days(m.occurred_at, now)) for m in mistakes)
    rate = penalty / analysed_questions
    score = max(0.0, 100.0 - rate * 40.0)
    by_category: dict[str, int] = {}
    for m in mistakes:
        by_category[m.category] = by_category.get(m.category, 0) + 1
    return FactorResult(
        score=round(score, 1),
        confidence=_confidence_from_count(analysed_questions, medium_at=5, high_at=15),
        evidence_count=len(mistakes),
        detail={"by_category": by_category, "analysed_questions": analysed_questions},
    )
