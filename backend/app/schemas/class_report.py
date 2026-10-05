"""The tutor's class report (task 8.6, AV-53, AV-112).

Every figure here is a count of rows that exist or a value another service
already computed, and carries what it was counted from (`PROD-1`). A missing
measurement is `None`, never 0 (`PROD-2`); a rate whose denominator is empty is
`None` for the same reason. This is the tutor's document: the parent's report is
a different one and is not derived from it by filtering.
"""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel

from app.schemas.today import ClassWeakTopic


class ReportReadiness(BaseModel):
    """The class headline, exactly as the class page prints it."""

    score: float | None = None
    predicted_grade: str | None = None
    status: str | None = None
    boundaries_missing: bool = False
    member_count: int = 0
    #: What the score was averaged over.
    students_with_evidence: int = 0


class UpNext(BaseModel):
    """The first lesson of the accepted plan that nothing has started."""

    scheduled_date: date
    chapter_code: str
    chapter_title: str
    topics: list[str]


class PlanReport(BaseModel):
    """Where the class is in its *accepted* teaching plan. A draft is never read."""

    has_plan: bool
    accepted_at: datetime | None = None
    exam_date: date | None = None
    #: Calendar days from the class's today to the exam. Negative once it has passed.
    days_to_exam: int | None = None
    #: Lessons the plan holds, cancelled ones excluded.
    lessons_planned: int | None = None
    lessons_taught: int | None = None
    lessons_left: int | None = None
    #: Lessons dated before today (and not still inside the auto-record's lag):
    #: the basis of `behind_by`. None until the plan has reached its first lesson.
    lessons_due: int | None = None
    #: Due lessons with no lesson recorded, by `plan_progress`'s one definition.
    behind_by: int | None = None
    #: Lessons taught before their planned date.
    ahead_by: int | None = None
    position: Literal["behind", "on_track", "ahead"] | None = None
    up_next: UpNext | None = None


class TopicReport(BaseModel):
    topic_id: int
    code: str
    title: str
    #: From `lesson_topics` (PROD-14): a lesson was recorded covering it.
    taught: bool
    #: The class mean of confident Topic Mastery rows; None = no measurement.
    avg_score: float | None = None
    #: How many learners the mean was taken over (None with no mean).
    student_count: int | None = None
    weak: bool = False
    includes_tutor_estimate: bool = False


class ChapterReport(BaseModel):
    #: None for the synthetic "Not in a chapter" group (topics with no chapter).
    chapter_id: int | None = None
    code: str
    title: str
    topics_total: int
    topics_taught: int
    state: Literal["not_started", "in_progress", "taught"]
    #: Planned / taught lesson counts for this chapter; None when the class has
    #: no accepted plan or the plan does not schedule the chapter.
    lessons_planned: int | None = None
    lessons_taught: int | None = None
    topics: list[TopicReport]


class MistakeCategoryReport(BaseModel):
    category_id: int
    category_name: str
    mistakes: int
    #: This category's mistakes / all tagged mistakes in the window.
    share: float
    students_affected: int
    severity_total: int


class MistakePatterns(BaseModel):
    since: date
    #: Questions the tagger examined in the window; the basis for every count.
    analysed_questions: int
    #: None when nothing was analysed: that is "not enough data", not a clean record.
    total_mistakes: int | None = None
    students_affected: int | None = None
    categories: list[MistakeCategoryReport]


class LearnerAttendance(BaseModel):
    student_id: int
    student_name: str
    present: int
    absent: int
    #: Lessons held with no mark for this learner: never read as absent.
    not_taken: int
    #: present / (present + absent); None when nothing was marked.
    rate: float | None = None


class AttendanceReport(BaseModel):
    present: int
    absent: int
    not_taken: int
    rate: float | None = None
    #: Lowest rate first, unmarked learners after, then by name.
    learners: list[LearnerAttendance]


class ClassReport(BaseModel):
    group_id: int
    name: str
    subject_name: str
    generated_at: datetime
    readiness: ReportReadiness
    plan: PlanReport
    chapters: list[ChapterReport]
    #: The shared weak-topic rule (the class page's), at the subject's threshold.
    weak_topics: list[ClassWeakTopic]
    weak_threshold: float
    mistakes: MistakePatterns
    attendance: AttendanceReport
