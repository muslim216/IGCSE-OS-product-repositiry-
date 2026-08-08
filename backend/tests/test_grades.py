"""grade_band derives a readiness band from a grade's *position* in its
subject's boundary list — never a percentage threshold (UX-28) — and is absent
when there is no grade, no boundaries, or the grade is unknown (PROD-2)."""

from app.services.grades import grade_band

# A full 9-1 IGCSE scale, highest grade first — the shape stored on Subject.
NINE_TO_ONE = [
    {"grade": g, "min": m}
    for g, m in [
        ("9", 90),
        ("8", 80),
        ("7", 70),
        ("6", 60),
        ("5", 50),
        ("4", 40),
        ("3", 30),
        ("2", 20),
        ("1", 10),
        ("U", 0),
    ]
]

# A full A*-U letter scale, highest first.
LETTER = [
    {"grade": g, "min": m}
    for g, m in [
        ("A*", 90),
        ("A", 80),
        ("B", 70),
        ("C", 60),
        ("D", 50),
        ("E", 40),
        ("F", 30),
        ("G", 20),
        ("U", 0),
    ]
]


def test_nine_to_one_scale_bands_by_index():
    for g in ("9", "8", "7"):
        assert grade_band(g, NINE_TO_ONE) == "on_track"
    for g in ("6", "5"):
        assert grade_band(g, NINE_TO_ONE) == "needs_attention"
    for g in ("4", "3", "2", "1", "U"):
        assert grade_band(g, NINE_TO_ONE) == "at_risk"


def test_letter_scale_bands_identically():
    # Same positions, different labels — the band is positional, not the grade.
    for g in ("A*", "A", "B"):
        assert grade_band(g, LETTER) == "on_track"
    for g in ("C", "D"):
        assert grade_band(g, LETTER) == "needs_attention"
    for g in ("E", "F", "G", "U"):
        assert grade_band(g, LETTER) == "at_risk"


def test_short_scale_does_not_overflow():
    # Fewer grades than there are bands: every grade lands in the top band and
    # nothing raises, rather than an IndexError past the end of the list.
    short = [
        {"grade": "A", "min": 66},
        {"grade": "B", "min": 33},
        {"grade": "C", "min": 0},
    ]
    assert grade_band("A", short) == "on_track"
    assert grade_band("B", short) == "on_track"
    assert grade_band("C", short) == "on_track"


def test_empty_boundaries_returns_none():
    # No boundaries means no band — not a defaulted one (PROD-2).
    assert grade_band("9", []) is None


def test_grade_absent_from_list_returns_none():
    assert grade_band("A", NINE_TO_ONE) is None


def test_no_grade_returns_none():
    # A subject with no confident evidence has predicted_grade None.
    assert grade_band(None, NINE_TO_ONE) is None
