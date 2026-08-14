from pydantic import BaseModel

from app.schemas.groups import UpcomingScheduleSlot


class ClassStripRow(BaseModel):
    """One class on the tutor's home strip.

    Every absent measurement is null, never 0: a class with no confident
    evidence has `score`, `predicted_grade` and `status` all null and renders as
    "not enough data yet" (PROD-2, UX-19). Coverage travels as a pair so a
    surface can say `9/11` rather than implying the score speaks for the whole
    class — a status without coverage is a claim about a class made from part
    of it.
    """

    group_id: int
    name: str
    subject_name: str
    score: float | None = None
    predicted_grade: str | None = None
    #: on_track | needs_attention | at_risk, from the predicted grade's position
    #: in its boundary list (never a percentage threshold — UX-28). null when
    #: there is no grade or no boundaries.
    status: str | None = None
    #: True when the subject has no boundaries in either source, so the surface
    #: can offer "Set them →" instead of silently showing no grade.
    boundaries_missing: bool = False
    member_count: int = 0
    students_with_evidence: int = 0
    awaiting_review_count: int = 0


class TodayView(BaseModel):
    """Everything the tutor's home needs, in one response and a bounded number
    of queries — replacing a per-class fan-out that itself looped per learner."""

    #: The class strip, exceptions first: at_risk, then needs_attention, then
    #: the healthy ones (which the surface collapses to a single line).
    classes: list[ClassStripRow]
    #: Today's lessons in the organization's timezone, not the server's.
    lessons: list[UpcomingScheduleSlot]
    #: How many submissions are waiting on the tutor's decision, across classes.
    review_count: int
    #: Verdict inputs the surface composes its first sentence from, so the rule
    #: lives in one place rather than being re-derived per surface.
    class_count: int
    joined_student_count: int
    classes_with_evidence: int


class ClassLearnerRow(BaseModel):
    """One learner on the class page.

    `direction` is what NEEDS YOU selects on, not `status`: a learner sliding
    from a grade 8 to a 6 is the one the tutor can still help, while a learner
    who has been a stable grade 4 all year is why the class carries its status
    but is not news. null means too little history to say — rendered as no
    arrow at all, never "flat", which would be a claim (UX-31, PROD-2).
    """

    student_id: int
    student_name: str
    score: float | None = None
    predicted_grade: str | None = None
    status: str | None = None
    direction: str | None = None


class ClassOverview(BaseModel):
    """The class page's headline: the same verdict inputs as the home's strip,
    plus the per-learner rows and the topic weaknesses behind them."""

    group_id: int
    name: str
    subject_name: str
    score: float | None = None
    predicted_grade: str | None = None
    status: str | None = None
    boundaries_missing: bool = False
    member_count: int = 0
    students_with_evidence: int = 0
    #: Learners whose direction is "down" — selected on direction, not level.
    needs_you: list[ClassLearnerRow]
    #: Every enrolled learner with confident evidence, lowest score first.
    learners: list[ClassLearnerRow]
    #: The class's weakest topics, lowest average first.
    weak_topics: list["ClassWeakTopic"]


class ClassWeakTopic(BaseModel):
    topic_code: str
    topic_title: str
    avg_score: float
    student_count: int


ClassOverview.model_rebuild()
