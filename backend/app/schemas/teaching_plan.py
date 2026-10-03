from datetime import date

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


class PlanInputsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    exam_date: date
    lessons_per_week: int
    lesson_minutes: int
    past_paper_start_date: date | None
    breaks: list[PlanBreakOut]


class TimetableDefaultsOut(BaseModel):
    #: Both None when the class has no timetable: nothing is pre-filled.
    lessons_per_week: int | None
    lesson_minutes: int | None


class PlanOverview(BaseModel):
    """Draft and accepted are separate: a class can hold both (6.1), and either may be null."""

    draft: PlanInputsOut | None
    accepted: PlanInputsOut | None
    timetable_defaults: TimetableDefaultsOut
