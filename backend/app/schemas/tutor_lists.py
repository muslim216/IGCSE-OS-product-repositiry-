from datetime import datetime

from pydantic import BaseModel


class TutorHomeworkRow(BaseModel):
    """One piece of homework in the cross-class Homework list. The three counts
    are plain tallies of rows, nothing derived: no score, no readiness."""

    id: int
    title: str
    status: str
    due_at: datetime | None
    created_at: datetime
    group_id: int
    group_name: str
    subject_name: str
    enrolled_count: int
    submitted_count: int
    marked_count: int


class TutorStudentClass(BaseModel):
    group_id: int
    group_name: str
    subject_name: str


class TutorStudentRow(BaseModel):
    id: int
    name: str
    classes: list[TutorStudentClass]


class TutorHomeworkList(BaseModel):
    """`truncated` is true only when the server left rows out; `limit` is the cap
    it applied, so the page can name it without mirroring the number."""

    items: list[TutorHomeworkRow]
    truncated: bool
    limit: int


class TutorStudentList(BaseModel):
    items: list[TutorStudentRow]
    truncated: bool
    limit: int
