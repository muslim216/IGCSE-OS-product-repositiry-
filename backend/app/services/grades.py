"""Map a readiness percentage to a predicted grade using a subject's editable
grade boundaries. Always presented to users as an estimate."""


def predict_grade(score_pct: float, grade_boundaries: list[dict]) -> str:
    """grade_boundaries is an ordered list of {"grade": str, "min": number},
    highest first. Returns the grade whose min the score meets."""
    if not grade_boundaries:
        return "—"
    for band in grade_boundaries:
        if score_pct >= band["min"]:
            return band["grade"]
    # Below the lowest boundary — return the last (lowest) grade.
    return grade_boundaries[-1]["grade"]
