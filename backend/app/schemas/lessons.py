from datetime import date as date_
from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.groups import TopicOut


class LessonCreate(BaseModel):
    group_id: int
    date: date_
    duration_min: int = Field(default=60, ge=15, le=480)
    notes: str | None = None
    schedule_slot_id: int | None = None


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
