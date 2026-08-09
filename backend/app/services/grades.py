"""Map a readiness percentage to a predicted grade using a subject's editable
grade boundaries, and map that predicted grade to a readiness band (the colour
a surface shows). Both are always presented to users as estimates."""


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


# The band is the grade's *position* in the boundary list, never a percentage:
# the top three grades read "on track", the next two "need attention", and
# every grade below that "at risk". Positional, so one rule fits a 9-1 scale,
# an A*-U scale, or any custom list a tutor uploads — and no literal grade or
# percentage threshold ever lives in a surface, style or constant (UX-28). The
# cut-offs are indices, so a scale shorter than five grades simply never reaches
# the lower bands (a three-grade list is all "on track") rather than raising.
# The three return values match the frontend ReadinessStatus union.
_ON_TRACK_MAX_INDEX = 2  # indices 0-2 — e.g. 9 8 7, or A* A B
_NEEDS_ATTENTION_MAX_INDEX = 4  # indices 3-4 — e.g. 6 5, or C D


def grade_band(grade: str | None, grade_boundaries: list[dict]) -> str | None:
    """The readiness band for a predicted grade, derived from that grade's
    position in the subject's ordered boundary list (highest grade first).

    Returns None when there is no grade, no boundaries, or the grade is absent
    from the list — an absent band is shown as absent, never defaulted to a
    colour (PROD-2).

    RISK-5: two boundary sources exist — the global Subject.grade_boundaries and
    the org-scoped GradeBoundary override read by the v2 engine. This function
    reads the grade *ordering* from whichever list the caller passes (today
    always Subject.grade_boundaries). The two sources share the same grade
    labels for a subject, so the position — and therefore the band — is the same
    whichever the grade was predicted against; only the percentage cut-offs
    differ. Converging the two sources is out of scope for this change.
    """
    if grade is None or not grade_boundaries:
        return None
    index = next(
        (i for i, band in enumerate(grade_boundaries) if band["grade"] == grade),
        None,
    )
    if index is None:
        return None
    if index <= _ON_TRACK_MAX_INDEX:
        return "on_track"
    if index <= _NEEDS_ATTENTION_MAX_INDEX:
        return "needs_attention"
    return "at_risk"
