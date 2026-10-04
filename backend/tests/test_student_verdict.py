"""Coherence C.1: one verdict per (student, subject), shared by every role."""

from app.services.student_verdict import (
    MAX_REASON_TOPICS,
    NOT_ENOUGH_DATA,
    student_verdict,
)

BOUNDARIES = [
    {"grade": "9", "min": 90},
    {"grade": "8", "min": 80},
    {"grade": "7", "min": 70},
    {"grade": "6", "min": 60},
    {"grade": "5", "min": 50},
    {"grade": "4", "min": 40},
    {"grade": "U", "min": 0},
]


def test_no_score_is_not_enough_data_never_a_verdict_from_nothing():
    v = student_verdict(score=None, predicted_grade=None, boundaries=BOUNDARIES, weak_topics=[])
    assert v.status == NOT_ENOUGH_DATA
    assert v.reason_topics == []
    assert v.next_step  # still says what unblocks it


def test_score_without_boundaries_is_not_enough_data():
    v = student_verdict(score=70.0, predicted_grade="7", boundaries=[], weak_topics=["A"])
    assert v.status == NOT_ENOUGH_DATA
    assert v.reason_topics == []


def test_grade_absent_from_boundaries_is_not_enough_data():
    v = student_verdict(score=70.0, predicted_grade="Z", boundaries=BOUNDARIES, weak_topics=[])
    assert v.status == NOT_ENOUGH_DATA


def test_top_three_grades_are_on_track_and_name_no_topics():
    v = student_verdict(score=75.0, predicted_grade="7", boundaries=BOUNDARIES, weak_topics=["X"])
    assert v.status == "on_track"
    assert v.reason_topics == []


def test_boundary_between_on_track_and_needs_attention():
    on = student_verdict(score=71, predicted_grade="7", boundaries=BOUNDARIES, weak_topics=[])
    off = student_verdict(score=65, predicted_grade="6", boundaries=BOUNDARIES, weak_topics=[])
    assert (on.status, off.status) == ("on_track", "needs_attention")


def test_boundary_between_needs_attention_and_at_risk():
    a = student_verdict(score=50, predicted_grade="5", boundaries=BOUNDARIES, weak_topics=[])
    b = student_verdict(score=45, predicted_grade="4", boundaries=BOUNDARIES, weak_topics=[])
    assert (a.status, b.status) == ("needs_attention", "at_risk")


def test_reasons_are_the_weakest_topics_capped():
    topics = ["Ionic bonding", "Moles", "Rates", "Acids"]
    v = student_verdict(score=62.0, predicted_grade="6", boundaries=BOUNDARIES, weak_topics=topics)
    assert v.reason_topics == topics[:MAX_REASON_TOPICS]
    assert "Ionic bonding" in v.next_step
    assert "Acids" not in v.next_step


def test_needs_attention_with_no_weak_topic_still_has_a_next_step():
    v = student_verdict(score=62.0, predicted_grade="6", boundaries=BOUNDARIES, weak_topics=[])
    assert v.status == "needs_attention"
    assert v.reason_topics == []
    assert v.next_step


def test_does_not_mutate_input():
    topics = ["a", "b", "c", "d"]
    student_verdict(score=62.0, predicted_grade="6", boundaries=BOUNDARIES, weak_topics=topics)
    assert topics == ["a", "b", "c", "d"]
