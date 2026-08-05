"""Pure-function tests for the Readiness Engine — no database."""

from datetime import datetime, timedelta, timezone

from app.models import EvidenceSource, ReadinessConfidence
from app.services.grades import predict_grade
from app.services.readiness import (
    EvidencePoint,
    compute_topic,
    subject_readiness,
)

NOW = datetime(2026, 7, 1, tzinfo=timezone.utc)


def point(source, score, days_ago):
    return EvidencePoint(source=source, score_pct=score, occurred_at=NOW - timedelta(days=days_ago))


def test_no_evidence_is_none_confidence():
    result = compute_topic([], NOW)
    assert result.score == 0.0
    assert result.confidence == ReadinessConfidence.none
    assert result.evidence_count == 0


def test_single_recent_piece_is_low_confidence():
    result = compute_topic([point(EvidenceSource.homework, 80, 1)], NOW)
    assert result.score == 80.0
    assert result.confidence == ReadinessConfidence.low


def test_three_recent_pieces_reach_high_confidence():
    points = [
        point(EvidenceSource.homework, 70, 2),
        point(EvidenceSource.homework, 80, 5),
        point(EvidenceSource.homework, 90, 8),
    ]
    result = compute_topic(points, NOW)
    assert result.confidence == ReadinessConfidence.high
    assert result.evidence_count == 3


def test_recent_evidence_dominates_via_decay():
    # An old poor score and a fresh strong score: recent should pull the mean up.
    points = [
        point(EvidenceSource.homework, 20, 120),  # ~2.7 half-lives old
        point(EvidenceSource.homework, 90, 1),
    ]
    result = compute_topic(points, NOW)
    assert result.score > 70  # fresh 90 dominates the stale 20


def test_mock_outweighs_homework():
    # Same recency, mock (1.5x) vs homework (1.0x): score leans toward the mock.
    points = [
        point(EvidenceSource.mock, 40, 3),
        point(EvidenceSource.homework, 100, 3),
    ]
    result = compute_topic(points, NOW)
    # Weighted mean = (1.5*40 + 1.0*100)/(2.5) = 64
    assert 63 <= result.score <= 65


def test_subject_readiness_ignores_no_evidence_topics():
    strong = compute_topic([point(EvidenceSource.mock, 90, 1)], NOW)
    empty = compute_topic([], NOW)
    # Empty topic (confidence none) must not drag the subject to 0.
    result = subject_readiness([(strong, 1.0), (empty, 2.0)])
    assert result == 90.0


def test_subject_readiness_weights_topics():
    a = compute_topic([point(EvidenceSource.mock, 100, 1)], NOW)
    b = compute_topic([point(EvidenceSource.mock, 40, 1)], NOW)
    # Topic b weighted 3x: (1*100 + 3*40)/4 = 55
    result = subject_readiness([(a, 1.0), (b, 3.0)])
    assert result == 55.0


def test_predict_grade_9_1():
    boundaries = [
        {"grade": "9", "min": 90},
        {"grade": "7", "min": 70},
        {"grade": "4", "min": 40},
        {"grade": "U", "min": 0},
    ]
    assert predict_grade(95, boundaries) == "9"
    assert predict_grade(72, boundaries) == "7"
    assert predict_grade(40, boundaries) == "4"
    assert predict_grade(10, boundaries) == "U"


def test_predict_grade_o_level():
    boundaries = [
        {"grade": "A*", "min": 90},
        {"grade": "A", "min": 80},
        {"grade": "C", "min": 60},
        {"grade": "U", "min": 0},
    ]
    assert predict_grade(85, boundaries) == "A"
    assert predict_grade(60, boundaries) == "C"


def test_predict_grade_empty_boundaries():
    assert predict_grade(50, []) == "—"
