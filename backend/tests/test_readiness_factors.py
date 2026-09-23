"""Pure-function tests for Readiness Engine v2's Layer 1 factor services —
no database, mirroring tests/test_readiness_engine.py's style for v1."""

from datetime import date, datetime, timedelta, timezone

from app.models import FactorConfidence
from app.services.readiness_factors import (
    NO_DATA,
    AssessmentPoint,
    HomeworkPoint,
    MarkedQuestion,
    MistakePoint,
    PastPaperAttemptPoint,
    TopicCoverage,
    assessment_performance,
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


def test_homework_score_is_accuracy_over_marked_work_only():
    points = [
        HomeworkPoint(submitted=True, pct=80),
        HomeworkPoint(submitted=True, pct=100),
        HomeworkPoint(submitted=False, pct=None),
    ]
    result = homework_performance(points)
    assert result.score == 90.0  # completion no longer blended in (AV-32)
    assert result.evidence_count == 2  # marked pieces, not assignments
    assert result.detail["completion_rate"] == 0.67
    assert result.detail["assignment_count"] == 3
    assert result.detail["marked_count"] == 2


def test_homework_nothing_marked_is_no_data_but_keeps_completion():
    # Handed in, awaiting marking: no accuracy exists yet — never a 0 (PROD-2).
    points = [HomeworkPoint(submitted=True, pct=None), HomeworkPoint(submitted=False, pct=None)]
    result = homework_performance(points)
    assert result.score is None
    assert result.confidence == FactorConfidence.no_data
    assert result.detail["completion_rate"] == 0.5  # submitted counts as done
    assert result.detail["submitted_count"] == 1


def test_homework_submitted_but_unmarked_counts_as_completed():
    points = [HomeworkPoint(submitted=True, pct=None), HomeworkPoint(submitted=True, pct=70)]
    assert homework_performance(points).detail["completion_rate"] == 1.0


def test_homework_detail_carries_no_punctuality():
    # Decision 5: punctuality is invisible until the weekly send (8.2).
    result = homework_performance([HomeworkPoint(submitted=True, pct=50)])
    assert "on_time_rate" not in result.detail


def test_homework_no_assignments_is_no_data():
    assert homework_performance([]) is NO_DATA


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
    assert mistake_analysis([], analysed_questions=0).confidence == FactorConfidence.no_data


def test_mistake_analysis_clean_record_scores_high():
    result = mistake_analysis([], analysed_questions=20, now=NOW)
    assert result.score == 100.0
    assert result.confidence == FactorConfidence.high


def test_mistake_analysis_penalizes_severe_recent_mistakes():
    mistakes = [
        MistakePoint(category="content_gap", severity=3, occurred_at=NOW - timedelta(days=1)),
        MistakePoint(category="careless", severity=1, occurred_at=NOW - timedelta(days=1)),
    ]
    result = mistake_analysis(mistakes, analysed_questions=10, now=NOW)
    assert result.score < 100.0
    assert result.detail["by_category"] == {"content_gap": 1, "careless": 1}


def test_mistake_analysis_scores_a_clean_record_when_work_was_analysed():
    result = mistake_analysis([], 12)
    assert result is not NO_DATA
    assert result.score == 100.0
    assert result.detail["analysed_questions"] == 12
