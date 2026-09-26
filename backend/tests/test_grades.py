"""predict_grade maps a score through tutor-entered boundaries (PROD-6). Moved
here from test_readiness_engine.py when 5.3b deleted the v1 engine it sat beside."""

from app.services.grades import predict_grade


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
