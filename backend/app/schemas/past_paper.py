from datetime import date, datetime

from pydantic import BaseModel


class PastPaperQuestionOut(BaseModel):
    id: int
    number: str
    text_summary: str
    max_marks: int
    has_mark_scheme: bool


class PastPaperOut(BaseModel):
    id: int
    subject_id: int
    session_label: str
    paper_number: str
    total_marks: int | None
    duration_minutes: int | None
    booklet_name: str | None
    # Present for tutors only — students must never see the mark scheme.
    mark_scheme_name: str | None = None
    extraction_error: str | None = None
    question_count: int = 0


class PastPaperDetail(PastPaperOut):
    questions: list[PastPaperQuestionOut] = []


class ExaminerReportOut(BaseModel):
    id: int
    subject_id: int
    paper_number: str
    session_label: str
    file_name: str
    # Whether this requester uploaded it, so the UI knows who may replace it
    # without leaking which tutor did.
    can_manage: bool = False


class PastPaperAttemptOut(BaseModel):
    submission_id: int
    past_paper_id: int
    session_label: str
    paper_number: str
    subject_name: str
    status: str
    timed: bool
    time_taken_minutes: int | None
    attempted_at: date | None
    submitted_at: datetime
    # Null until the attempt has settled.
    raw_marks: int | None = None
    max_marks: int | None = None
