from datetime import date, datetime, time

from pydantic import BaseModel, ConfigDict, Field, model_validator

#: Here and not in the service, because services import schemas and not the reverse.
LESSONS_PER_WEEK_RANGE = (1, 14)
LESSON_MINUTES_RANGE = (15, 300)


class PlanBreakOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    start_date: date
    end_date: date
    label: str


class PlanBreakCreate(BaseModel):
    start_date: date
    end_date: date
    label: str = Field(min_length=1, max_length=120)

    @model_validator(mode="after")
    def _ordered(self) -> "PlanBreakCreate":
        if self.end_date < self.start_date:
            raise ValueError("A break cannot end before it starts")
        return self


class PlanInputsIn(BaseModel):
    exam_date: date
    lessons_per_week: int = Field(ge=LESSONS_PER_WEEK_RANGE[0], le=LESSONS_PER_WEEK_RANGE[1])
    lesson_minutes: int = Field(ge=LESSON_MINUTES_RANGE[0], le=LESSON_MINUTES_RANGE[1])
    #: None means past papers have not been scheduled to start (`DB-9`).
    past_paper_start_date: date | None = None

    @model_validator(mode="after")
    def _papers_before_exam(self) -> "PlanInputsIn":
        if self.past_paper_start_date and self.past_paper_start_date > self.exam_date:
            raise ValueError("Past papers cannot start after the exam date")
        return self


class PlanSlotOut(BaseModel):
    id: int
    chapter_id: int
    chapter_code: str
    chapter_title: str
    scheduled_date: date
    sequence: int
    #: generated | manually_modified | confirmed | completed
    provenance: str
    #: Local wall clock in the organization's zone: the slot's own, else the
    #: weekly timetable's for that weekday. None = unknown, never midnight.
    start_time: time | None = None
    #: The tutor cancelled this lesson; the row is kept as the record of intent.
    cancelled: bool = False
    #: The lesson recorded against this slot, and who recorded it (tutor | plan):
    #: `plan` means it was recorded from the plan because nobody said otherwise.
    lesson_id: int | None = None
    lesson_origin: str | None = None


class PlanSlotPatch(BaseModel):
    """Any one field alone is an edit; none is not."""

    scheduled_date: date | None = None
    chapter_id: int | None = None
    #: Local wall clock in the organization's zone.
    start_time: time | None = None

    @model_validator(mode="after")
    def _something_to_change(self) -> "PlanSlotPatch":
        if self.scheduled_date is None and self.chapter_id is None and self.start_time is None:
            raise ValueError("Give a new date, chapter or start time")
        return self


class ChapterReasonOut(BaseModel):
    chapter_id: int
    #: None when the chapter has since been removed from the subject.
    chapter_code: str | None
    chapter_title: str | None
    weight: float
    #: None when the weights did not come from the AI (an even or stored split).
    reason: str | None


class ReflowOut(BaseModel):
    """What the last automatic reflow for a syllabus change did (task 6.8)."""

    #: reflowed | failed | skipped
    status: str
    #: ISO-8601 UTC instant of the reflow.
    at: str | None
    #: Why a skipped reflow did nothing.
    reason: str | None
    #: Why a failed reflow could not reshuffle the plan.
    failure_message: str | None
    #: When the plan last reflowed successfully, kept across a later failure.
    last_success_at: str | None


class DraftOutcomeOut(BaseModel):
    """What the last drafting run did, for the tutor (PROD-1, PROD-2)."""

    #: drafted | failed | skipped | stale (inputs or breaks changed since the draft)
    status: str
    drafted_at: str | None
    #: ai | stored_chapter_weights | ai_unusable | None
    weight_source: str | None
    degraded_reason: str | None
    guidance_used: bool
    guidance_note: str | None
    defaulted_chapters: int
    chapters: list[ChapterReasonOut]
    failure_code: str | None
    failure_message: str | None
    #: None when no syllabus change has triggered a reflow of this plan.
    reflow: ReflowOut | None = None


class PlanInputsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    exam_date: date
    lessons_per_week: int
    lesson_minutes: int
    past_paper_start_date: date | None
    breaks: list[PlanBreakOut]
    #: Ordered by (scheduled_date, sequence). Empty until a draft is generated.
    slots: list[PlanSlotOut] = []
    #: None until the plan has been drafted at least once.
    outcome: DraftOutcomeOut | None = None
    #: A draft job for this plan is queued or running.
    drafting: bool = False
    #: The latest draft job for this plan failed outright (a provider fault
    #: that retries did not clear); `outcome` may then describe an older run.
    draft_job_failed: bool = False
    accepted_at: datetime | None = None


class TimetableDefaultsOut(BaseModel):
    #: Both None when the class has no timetable: nothing is pre-filled.
    lessons_per_week: int | None
    lesson_minutes: int | None


class NextLessonChapterOut(BaseModel):
    id: int
    code: str
    title: str


class PlanProgressOut(BaseModel):
    """How the accepted plan compares with the lessons recorded (task 6.6, AV-18).

    "Not recorded", never "missed": a lesson may have been taught and not logged."""

    #: Planned lessons dated before the tutor's today.
    planned_to_date: int
    #: Of those, the ones with a lesson recorded.
    taught_to_date: int
    #: Planned lessons before today with no lesson recorded. Behind means > 0.
    missed: int
    earliest_missed_date: date | None
    earliest_missed_chapter: NextLessonChapterOut | None


class PlanOverview(BaseModel):
    """Draft and accepted are separate: a class can hold both (6.1), and either may be null."""

    draft: PlanInputsOut | None
    accepted: PlanInputsOut | None
    timetable_defaults: TimetableDefaultsOut
    #: For the accepted plan only; None when there is none (never a fabricated 0).
    progress: PlanProgressOut | None = None


class NextLessonTopicOut(BaseModel):
    id: int
    code: str
    title: str


class NextLessonOut(BaseModel):
    """The accepted plan's next unstarted slot and its chapter's topics (task 6.5).

    A suggestion only: it pre-fills the add-lesson form and writes nothing."""

    slot_id: int
    scheduled_date: date
    chapter: NextLessonChapterOut
    topics: list[NextLessonTopicOut]


class CancelSlotOut(BaseModel):
    """The result of cancelling one planned lesson (task 7.4, AV-120)."""

    #: True when later lessons moved up to make room for the cancelled one's content.
    shifted: bool
    #: How many lessons moved, the replacement included.
    moved: int
    #: Set when nothing could be rescheduled: the lesson stays cancelled and the
    #: tutor is told how to catch up.
    message: str | None = None
    plan: PlanOverview


class LessonReminderOut(BaseModel):
    """A planned lesson starting within 15 minutes (or under way), for the tutor
    (task 7.4, AV-120). Computed at read time from the accepted plan."""

    slot_id: int
    group_id: int
    group_name: str
    scheduled_date: date
    #: Local wall clock in the organization's zone.
    start_time: time
    #: The same moment as a UTC instant, for a countdown.
    starts_at: datetime
    chapter: NextLessonChapterOut
    #: What the plan says this lesson covers: its share of the chapter's topics.
    topics: list[NextLessonTopicOut]
