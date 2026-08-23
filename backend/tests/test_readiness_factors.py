"""Pure-function tests for Readiness Engine v2's Layer 1 factor services —
no database, mirroring tests/test_readiness_engine.py's style for v1."""

from datetime import date, datetime, timedelta, timezone

from app.models import FactorConfidence
from app.services.readiness_factors import (
    AssessmentPoint,
    ConsistencyPoint,
    HomeworkPoint,
    MarkedQuestion,
    MistakePoint,
    PastPaperAttemptPoint,
    TopicCoverage,
    assessment_performance,
    consistency,
    homework_performance,
    mistake_analysis,
    past_paper_performance,
    syllabus_coverage,
    topic_mastery,
)

NOW = datetime(2026, 7, 1, tzinfo=timezone.utc)


# ---- Topic Mastery ----


def test_topic_mastery_no_data():
    result = topic_mastery([], NOW)
    assert result.score is None
    assert result.confidence == FactorConfidence.no_data


def test_topic_mastery_hard_questions_weighted_more():
    easy_only = topic_mastery(
        [MarkedQuestion(difficulty="easy", pct=100, occurred_at=NOW - timedelta(days=1))], NOW
    )
    hard_only = topic_mastery(
        [MarkedQuestion(difficulty="hard", pct=100, occurred_at=NOW - timedelta(days=1))], NOW
    )
    # Same pct either way (only one point each), but the detail breakdown
    # should reflect which tier was attempted.
    assert easy_only.detail["by_difficulty"] == {"easy": 100.0}
    assert hard_only.detail["by_difficulty"] == {"hard": 100.0}


def test_topic_mastery_mixed_tiers_blend():
    points = [
        MarkedQuestion(difficulty="easy", pct=100, occurred_at=NOW - timedelta(days=1)),
        MarkedQuestion(difficulty="hard", pct=40, occurred_at=NOW - timedelta(days=1)),
    ]
    result = topic_mastery(points, NOW)
    # weighted = (0.8*100 + 1.3*40) / (0.8+1.3) = 132/2.1 = 62.9
    assert 60 <= result.score <= 65
    assert result.evidence_count == 2


# ---- Past Paper Performance ----


def test_past_paper_no_attempts():
    assert past_paper_performance([]).confidence == FactorConfidence.no_data


def test_past_paper_trend_improving():
    attempts = [
        PastPaperAttemptPoint(pct=50, timed=True, attempted_at=date(2026, 1, 1)),
        PastPaperAttemptPoint(pct=60, timed=True, attempted_at=date(2026, 3, 1)),
        PastPaperAttemptPoint(pct=80, timed=False, attempted_at=date(2026, 5, 1)),
        PastPaperAttemptPoint(pct=90, timed=True, attempted_at=date(2026, 6, 1)),
    ]
    result = past_paper_performance(attempts)
    assert result.score == 70.0
    assert result.detail["trend"] > 0
    assert result.detail["timed_ratio"] == 0.75


# ---- Homework Performance ----


def test_homework_accuracy_averages_over_submitted_work_only():
    """A missed assignment lowers completion; it must not be averaged into
    accuracy as a zero (PROD-2). The regression this guards is a plausible
    narrowing of `pct is not None` that keeps the full point count in the
    denominator: that reads 50.0 here instead of 100.0."""
    points = [
        HomeworkPoint(pct=100, on_time=True),
        HomeworkPoint(pct=None, on_time=None),
    ]
    result = homework_performance(points)
    assert result.detail["accuracy"] == 100.0


def test_homework_no_submissions_scores_zero_completion():
    points = [HomeworkPoint(pct=None, on_time=None), HomeworkPoint(pct=None, on_time=None)]
    result = homework_performance(points)
    assert result.score == 0.0
    assert result.detail["accuracy"] is None


def test_homework_blends_accuracy_and_completion():
    points = [
        HomeworkPoint(pct=100, on_time=True),
        HomeworkPoint(pct=100, on_time=True),
        HomeworkPoint(pct=None, on_time=None),  # missed
        HomeworkPoint(pct=None, on_time=None),  # missed
    ]
    result = homework_performance(points)
    # accuracy=100, completion=0.5 -> 100*0.7 + 50*0.3 = 85
    assert result.score == 85.0
    assert result.detail["completion_rate"] == 0.5


# ---- Assessment Performance ----


def test_assessment_performance_decay_weighted():
    points = [
        AssessmentPoint(pct=40, occurred_at=NOW - timedelta(days=200)),
        AssessmentPoint(pct=90, occurred_at=NOW - timedelta(days=1)),
    ]
    result = assessment_performance(points, NOW)
    assert result.score > 70  # recent 90 dominates the stale 40


# ---- Syllabus Coverage ----


def test_syllabus_coverage_no_topics():
    assert syllabus_coverage([]).confidence == FactorConfidence.no_data


def test_syllabus_coverage_blends_taught_practiced_mastered():
    topics = [
        TopicCoverage(taught=True, practiced=True, mastered=True),
        TopicCoverage(taught=True, practiced=True, mastered=False),
        TopicCoverage(taught=True, practiced=False, mastered=False),
        TopicCoverage(taught=False, practiced=False, mastered=False),
    ]
    result = syllabus_coverage(topics)
    assert result.detail["topics_total"] == 4
    assert result.detail["topics_taught"] == 3
    assert result.detail["topics_practiced"] == 2
    assert result.detail["topics_mastered"] == 1
    assert 0 < result.score < 100


# ---- Mistake Analysis ----


def test_mistake_analysis_no_questions_is_no_data():
    assert mistake_analysis([], total_questions=0).confidence == FactorConfidence.no_data


def test_mistake_analysis_clean_record_scores_high():
    result = mistake_analysis([], total_questions=20, now=NOW)
    assert result.score == 100.0
    assert result.confidence == FactorConfidence.high


def test_mistake_analysis_penalizes_severe_recent_mistakes():
    mistakes = [
        MistakePoint(category="content_gap", severity=3, occurred_at=NOW - timedelta(days=1)),
        MistakePoint(category="careless", severity=1, occurred_at=NOW - timedelta(days=1)),
    ]
    result = mistake_analysis(mistakes, total_questions=10, now=NOW)
    assert result.score < 100.0
    assert result.detail["by_category"] == {"content_gap": 1, "careless": 1}


# ---- Consistency ----


def test_consistency_no_assignments_is_no_data():
    assert consistency([]).confidence == FactorConfidence.no_data


def test_consistency_rewards_completion_and_timeliness():
    points = [
        ConsistencyPoint(
            due_at=NOW - timedelta(days=5), submitted_at=NOW - timedelta(days=6)
        ),  # on time
        ConsistencyPoint(
            due_at=NOW - timedelta(days=5), submitted_at=NOW - timedelta(days=1)
        ),  # late
        ConsistencyPoint(due_at=NOW - timedelta(days=5), submitted_at=None),  # missed
    ]
    result = consistency(points)
    # completion = 2/3, on_time = 1/3 -> 2/3*60 + 1/3*40 = 40 + 13.3 = 53.3
    assert 50 <= result.score <= 55
