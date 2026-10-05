from datetime import date, datetime, time

from pydantic import BaseModel

from app.schemas.groups import UpcomingScheduleSlot
from app.schemas.readiness import SubjectVerdict


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


class ChapterPrompt(BaseModel):
    """A chapter the class's accepted plan has reached (or reaches within a
    week) that has no classified yet (AV-20, AV-22). Information only: the
    surface links to where one is uploaded and never gates on it."""

    group_id: int
    group_name: str
    subject_name: str
    chapter_id: int
    chapter_code: str
    chapter_title: str
    #: The chapter's first and last planned lesson dates in the accepted plan.
    starts_on: date
    ends_on: date
    #: True when the first lesson is today or earlier; False for the lookahead.
    started: bool


class BehindClass(BaseModel):
    """A class whose accepted plan has lessons dated before today with no lesson
    recorded (AV-18). Says "not recorded", not "missed": it may have been taught."""

    group_id: int
    group_name: str
    #: Planned lessons before today with no lesson recorded; always >= 1 here.
    missed: int
    earliest_missed_date: date
    chapter_id: int
    chapter_code: str
    chapter_title: str


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
    #: Chapters from accepted plans awaiting a classified, soonest first. Empty
    #: for a tutor with no plan; tutor-only because plans are (AV-19).
    chapter_prompts: list[ChapterPrompt] = []
    #: Classes behind their accepted plan, most not-recorded lessons first. Empty
    #: for a tutor with no plan; tutor-only because plans are (AV-19).
    behind_classes: list[BehindClass] = []


class ClassLearnerRow(BaseModel):
    """One learner on the class page.

    `direction` is what NEEDS YOU selects on, not the verdict: a learner sliding
    from a grade 8 to a 6 is the one the tutor can still help, while a learner
    who has been a stable grade 4 all year is why the class carries its status
    but is not news. null means too little history to say — rendered as no
    arrow at all, never "flat", which would be a claim (UX-31, PROD-2).
    """

    student_id: int
    student_name: str
    score: float | None = None
    predicted_grade: str | None = None
    # The shared verdict (services/student_verdict.py) — the same decision the
    # learner's profile, their own readiness and their parent's page show. It
    # replaces the row's old `status`: a learner with no score is
    # "not_enough_data" here, never a defaulted colour (PROD-2).
    verdict: SubjectVerdict
    direction: str | None = None
    # Completion is a fact, not part of the score (AV-32): "4 of 5 handed in"
    # carries its own denominator (PROD-1) and is never blended into a number.
    # Both None when the learner's latest run has no homework_performance row
    # — never 0, which PROD-2 forbids for an absent measurement.
    homework_assignment_count: int | None = None
    homework_submitted_count: int | None = None


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
    #: Every enrolled learner (fix round 1) — scored ones first, lowest score
    #: first, then unscored ones by name. An unscored row's score, grade and
    #: direction are null; its homework counts can still be real (AV-32).
    learners: list[ClassLearnerRow]
    #: The class's weakest topics, lowest average first.
    weak_topics: list["ClassWeakTopic"]


class ClassWeakTopic(BaseModel):
    topic_code: str
    topic_title: str
    avg_score: float
    student_count: int
    # True when any contributing learner's score rests on a tutor's estimate
    # rather than marked work alone (fix round 1, PROD-8, UX-20).
    includes_tutor_estimate: bool = False


ClassOverview.model_rebuild()


class WeekGlance(BaseModel):
    """The week-at-a-glance strip. Every figure carries what it was counted from
    (PROD-1) and a missing measurement is null, never 0 (PROD-2)."""

    week_start: date
    week_end: date
    #: Lessons this week: accepted-plan slots (cancelled ones excluded) plus
    #: lessons recorded this week that no slot of the week accounts for.
    lessons_planned: int
    lessons_taught: int
    #: The review queue's own count (same predicate as the Review page).
    marking_waiting: int
    #: Attendance this week over the tutor's classes, by the one definition in
    #: services/attendance.py. `rate` is present / (present + absent), null when
    #: nothing was marked; not-taken pairs are excluded from it and counted apart.
    attendance_present: int
    attendance_absent: int
    attendance_not_taken: int
    attendance_rate: float | None = None
    #: Students whose readiness fell by at least `readiness_drop_threshold`
    #: points against their latest snapshot at least 7 days old. A student with
    #: no such older snapshot is not in the comparison at all.
    readiness_drop_count: int
    readiness_compared_count: int
    readiness_drop_threshold: float


class ClassTopicRef(BaseModel):
    id: int
    code: str
    title: str


class AgendaItem(BaseModel):
    """One of today's lessons. Time-dependent wording (starting soon, under way,
    ended) is decided by the surface from `starts_at` / `ends_at`, so it stays
    right between refetches."""

    key: str
    group_id: int
    group_name: str
    subject_name: str
    #: The accepted plan's slot, when the lesson comes from (or is recorded
    #: against) one. Null for a timetable-only or ad-hoc lesson.
    slot_id: int | None = None
    #: The recorded lesson, when there is one.
    lesson_id: int | None = None
    #: plan | lesson | timetable — where this row came from (PROD-1).
    source: str
    start_time: time | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    duration_min: int | None = None
    chapter_id: int | None = None
    chapter_code: str | None = None
    chapter_title: str | None = None
    #: The lesson's share of its chapter's topics (the one split the
    #: next-lesson suggestion and the auto-record use).
    topics: list[ClassTopicRef] = []
    #: Today in the tutor's zone — what "Record" dates the lesson.
    local_date: date
    recorded: bool = False


class LastLessonAttendance(BaseModel):
    lesson_id: int
    lesson_date: date
    present: int
    absent: int
    not_taken: int


class ClassAttention(BaseModel):
    """The one thing about a class that most needs the tutor, with its reason
    already in words. `message` names the students and the topic; the surface
    links by `kind` plus the ids."""

    #: weak_topic | readiness_drop | behind_plan | marking
    kind: str
    message: str
    topic_id: int | None = None
    student_ids: list[int] = []
    student_names: list[str] = []


class ClassCard(BaseModel):
    group_id: int
    #: none | on_track | behind | complete
    plan_state: str
    plan_chapter_code: str | None = None
    plan_chapter_title: str | None = None
    #: Planned lessons before today with no lesson recorded (behind only).
    plan_missed: int = 0
    plan_earliest_missed_date: date | None = None
    #: Direction of the class's readiness against a week ago, over students who
    #: have both ends. null when no student has history to compare (PROD-2).
    readiness_direction: str | None = None
    readiness_compared_count: int = 0
    last_lesson: LastLessonAttendance | None = None
    #: Published assignments some enrolled student has not handed in, and how
    #: many hand-ins are missing in total.
    homework_out: int = 0
    homework_missing: int = 0
    attention: ClassAttention | None = None


class RemarkItem(BaseModel):
    submission_id: int
    assignment_title: str
    student_name: str
    group_name: str
    #: The student's reason, as written; null when they gave none.
    reason: str | None = None


class TodayOverview(BaseModel):
    week: WeekGlance
    agenda: list[AgendaItem]
    #: One card per class, in tutor_groups order; the surface re-orders by the
    #: home strip's exceptions-first order.
    classes: list[ClassCard]
    #: Open remark requests on submissions waiting in the tutor's queue.
    remarks: list[RemarkItem]
