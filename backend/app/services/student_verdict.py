"""One verdict per (student, subject), the same for tutor, student and parent.

Before this, three surfaces told three stories about one student on one day:
the tutor's badge said "Needs attention", the student's home said "You're
clear", the parent's page said "needs support" and then "Nothing is needed".
Each re-derived its own sentence. There is now one decision, made here, and the
roles differ only in *wording* (frontend/src/lib/studentVerdict.ts).

The status is the readiness band (`grade_band`: the predicted grade's position
in the tutor's own boundary list) — the same band every status badge already
shows. The reasons are the weak topics (at or below the tutor's threshold,
lowest first). No model is involved at any step (PROD-6).

The decision is pure (BE-4): values in, a `Verdict` out. The class loader is in
services/class_verdicts.py, which may import the readiness summary; this module
may not, because the summary imports it.
"""

from dataclasses import dataclass
from typing import cast

from app.schemas.readiness import VerdictStatus
from app.services.grades import grade_band

#: The status when there is nothing to base a verdict on (PROD-2). The other
#: three are `grade_band`'s own values, so the app has one status vocabulary.
NOT_ENOUGH_DATA: VerdictStatus = "not_enough_data"

#: A verdict names at most this many topics — a longer list stops being a
#: reason and becomes the whole syllabus.
MAX_REASON_TOPICS = 3


@dataclass(frozen=True)
class Verdict:
    #: "on_track" | "needs_attention" | "at_risk" | "not_enough_data"
    status: VerdictStatus
    #: Titles of the weakest topics below the tutor's threshold, lowest first.
    #: Empty for on_track and not_enough_data.
    reason_topics: list[str]
    #: One neutral instruction, identical for every role.
    next_step: str


def _join(names: list[str]) -> str:
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


def student_verdict(
    *,
    score: float | None,
    predicted_grade: str | None,
    boundaries: list[dict],
    weak_topics: list[str],
) -> Verdict:
    """`weak_topics` are titles, lowest score first, already filtered to the
    tutor's threshold. A verdict needs a score, boundaries to stand behind its
    grade, and a grade that is on the list; missing any, there is no status to
    give and it says so rather than defaulting to a colour (PROD-2)."""
    band = grade_band(predicted_grade, boundaries) if score is not None else None
    if band is None:
        return Verdict(
            status=NOT_ENOUGH_DATA,
            reason_topics=[],
            next_step="Marked work will build this picture.",
        )
    if band == "on_track":
        return Verdict(
            status="on_track", reason_topics=[], next_step="Nothing flagged in this subject."
        )
    reasons = list(weak_topics[:MAX_REASON_TOPICS])
    # A statement of what the data shows, never an instruction (AV-42).
    next_step = (
        f"Weakest right now: {_join(reasons)}." if reasons else "No single topic stands out."
    )
    return Verdict(status=cast(VerdictStatus, band), reason_topics=reasons, next_step=next_step)
