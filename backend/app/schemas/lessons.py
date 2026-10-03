from datetime import date as date_
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, Field

from app.schemas.groups import TopicOut


class LessonCreate(BaseModel):
    group_id: int
    date: date_
    duration_min: int = Field(default=60, ge=15, le=480)
    notes: str | None = None
    schedule_slot_id: int | None = None
    #: Syllabus topics covered, exactly as the tutor left them (task 6.5): a plan
    #: suggestion pre-fills these in the form but never writes them itself.
    topic_ids: list[Annotated[int, Field(ge=1)]] = Field(default_factory=list, max_length=500)
    #: The accepted plan's slot this lesson confirms (AV-17). A lesson is never
    #: created for a slot by anything but the tutor submitting this.
    plan_slot_id: Annotated[int, Field(ge=1)] | None = None


class LessonUpdate(BaseModel):
    date: date_ | None = None
    duration_min: int | None = Field(default=None, ge=15, le=480)
    notes: str | None = None


class LessonOut(BaseModel):
    id: int
    group_id: int
    date: date_
    duration_min: int
    notes: str | None
    schedule_slot_id: int | None
    topics: list[TopicOut]


class LessonTopicsUpdate(BaseModel):
    topic_ids: list[int]


class LessonObservationCreate(BaseModel):
    student_id: int
    topic_id: int | None = None
    body: str = Field(min_length=1)
    rating: int | None = Field(default=None, ge=0, le=100)


class LessonObservationOut(BaseModel):
    id: int
    lesson_id: int
    student_id: int
    topic_id: int | None
    body: str
    rating: int | None
    created_at: datetime
