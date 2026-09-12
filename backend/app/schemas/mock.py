from datetime import date, datetime

from pydantic import BaseModel

from app.models import AssessmentType, MockStatus


class MockQuestionOut(BaseModel):
    id: int
    number: str
    text_summary: str
    max_marks: int
    has_mark_scheme: bool


class MockOut(BaseModel):
    id: int
    subject_id: int
    group_id: int | None
    title: str
    type: AssessmentType
    sat_on: date | None
    status: MockStatus
    total_marks: int | None
    duration_minutes: int | None
    paper_name: str
    # Tutors only — a student who can read the scheme is not sitting a mock.
    mark_scheme_name: str | None = None
    extraction_error: str | None = None
    question_count: int = 0


class MockDetail(MockOut):
    questions: list[MockQuestionOut] = []


class MockSubmissionOut(BaseModel):
    submission_id: int
    mock_id: int
    title: str
    subject_name: str
    status: str
    submitted_at: datetime
    # Null until the submission has settled.
    raw_marks: int | None = None
    max_marks: int | None = None
