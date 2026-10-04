from datetime import date as date_
from datetime import datetime
from datetime import time as time_
from typing import Annotated

from pydantic import AfterValidator, BaseModel, Field

from app.models import (
    AttendanceSource,
    AttendanceState,
    LessonMode,
    LessonOrigin,
    MeetingProvider,
)
from app.schemas.groups import TopicOut


def _wall_clock(value: time_) -> time_:
    # A lesson's start is local wall-clock time in the class's zone (tutor override, else organization).
    # "17:00+02:00" would be stored as a bare 17:00 with its offset silently
    # dropped, so an offset is refused rather than half-honoured.
    if value.tzinfo is not None:
        raise ValueError("Give the start time without a timezone offset")
    return value


WallClockTime = Annotated[time_, AfterValidator(_wall_clock)]


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
    mode: LessonMode = LessonMode.in_person
    #: Local wall-clock time in the class's zone (tutor override, else organization); omitted = unknown.
    start_time: WallClockTime | None = None
    #: A Zoom or Google Meet link, online lessons only. Parsed server-side into
    #: provider + meeting id; anything else is a 422 (7.3).
    meeting_link: Annotated[str, Field(max_length=500)] | None = None


class LessonUpdate(BaseModel):
    date: date_ | None = None
    duration_min: int | None = Field(default=None, ge=15, le=480)
    notes: str | None = None
    mode: LessonMode | None = None
    start_time: WallClockTime | None = None
    #: An explicit null clears the link; omitting it leaves it.
    meeting_link: Annotated[str, Field(max_length=500)] | None = None


class LessonOut(BaseModel):
    id: int
    group_id: int
    date: date_
    duration_min: int
    notes: str | None
    schedule_slot_id: int | None
    mode: LessonMode
    start_time: time_ | None
    origin: LessonOrigin
    topics: list[TopicOut]
    meeting_provider: MeetingProvider | None = None
    #: Rebuilt from the stored provider + meeting id; a Zoom passcode is never kept.
    meeting_link: str | None = None


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


class AttendanceEntryIn(BaseModel):
    student_id: Annotated[int, Field(ge=1)]
    #: `null` clears the mark (not taken).
    state: AttendanceState | None


class AttendanceUpdate(BaseModel):
    entries: list[AttendanceEntryIn] = Field(max_length=500)


class AttendanceRowOut(BaseModel):
    student_id: int
    name: str
    #: `null` means attendance was not taken — never absent.
    state: AttendanceState | None
    source: AttendanceSource | None
    recorded_at: datetime | None
