from datetime import date, datetime

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


class PlanSlotPatch(BaseModel):
    """Either field alone is an edit; neither is not."""

    scheduled_date: date | None = None
    chapter_id: int | None = None

    @model_validator(mode="after")
    def _something_to_change(self) -> "PlanSlotPatch":
        if self.scheduled_date is None and self.chapter_id is None:
            raise ValueError("Give a new date or a new chapter")
        return self


class ChapterReasonOut(BaseModel):
    chapter_id: int
    #: None when the chapter has since been removed from the subject.
    chapter_code: str | None
    chapter_title: str | None
    weight: float
    #: None when the weights did not come from the AI (an even or stored split).
    reason: str | None


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


class PlanOverview(BaseModel):
    """Draft and accepted are separate: a class can hold both (6.1), and either may be null."""

    draft: PlanInputsOut | None
    accepted: PlanInputsOut | None
    timetable_defaults: TimetableDefaultsOut
