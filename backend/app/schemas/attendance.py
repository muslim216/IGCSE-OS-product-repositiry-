"""What a student, their parent and their tutor read about attendance (task 7.2).

Not a readiness factor (AV-33). `rate` is `null` when no lesson was marked."""

from datetime import date, time

from pydantic import BaseModel, ConfigDict

from app.models import AttendanceState, LessonMode


class RecentLessonOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    lesson_id: int
    date: date
    start_time: time | None
    mode: LessonMode
    #: `null` means attendance was not taken — never absent.
    state: AttendanceState | None


class ClassAttendanceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    group_id: int
    group_name: str
    lessons: int
    present: int
    absent: int
    not_taken: int
    #: present / (present + absent), 0..1; `null` when nothing was marked.
    rate: float | None
    recent: list[RecentLessonOut]


class StudentAttendanceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    lessons: int
    present: int
    absent: int
    not_taken: int
    rate: float | None
    classes: list[ClassAttendanceOut]
