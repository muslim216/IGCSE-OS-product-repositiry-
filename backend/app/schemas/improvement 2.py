"""Response contract for the improvement tab.

Read this as the security boundary it is: **every field below is either the
reader's own datum or a count.** There is no field that can hold a classmate's
score, grade, delta, name or identity, and adding one reopens the
de-anonymisation vectors documented in services/improvement.py. `member_count`
and `ranked_count` are cardinalities the reader already knows from their own
class list.
"""

from pydantic import BaseModel


class ImprovementPeriod(BaseModel):
    """One window: the reader's own movement, and where it placed them."""

    label: str
    # The reader's own change in readiness across the window. None when their
    # series does not span it — a stated absence, never a 0 (PROD-2).
    delta: float | None = None
    # The reader's own placing, or None when a gate is not met. None is a
    # complete answer: `delta` above still renders, and the surface says the
    # class is too small to compare rather than showing an empty board.
    rank: int | None = None
    # How many students had a delta for this window. A count, not a roster.
    ranked_count: int = 0
    # True when the placing must be shown as "in the second half" rather than as
    # a number — the bottom half, or a tie that spans the halfway line.
    banded: bool = False


class FocusTopic(BaseModel):
    topic_code: str
    topic_title: str
    # None when the topic carries no confident evidence: the surface says "not
    # enough data yet" rather than printing a score nothing stands behind.
    score: float | None = None


class SubjectImprovement(BaseModel):
    subject_id: int
    subject_name: str
    # The length of one window in days, so the surface states what "this month"
    # measured instead of leaving the reader to assume a calendar month.
    window_days: int
    # How many students are in the reader's classes for this subject. A count.
    member_count: int
    periods: list[ImprovementPeriod]
    focus: list[FocusTopic]
