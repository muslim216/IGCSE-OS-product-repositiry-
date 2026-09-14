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
    # Student list only (`GET /mocks/mine`): this student's own submission
    # status, or null if they have not sat it. `sat_on` is the tutor's sitting
    # date and says nothing about whether *this* student handed in, so a screen
    # asking "have I done this" has to read this rather than that. Null for a
    # tutor, who is looking at a class rather than at their own work.
    my_submission_status: str | None = None


class MockAssignGroup(BaseModel):
    """PATCH body for /mocks/{mock_id}: the only field that route can set."""

    group_id: int


class MockDetail(MockOut):
    questions: list[MockQuestionOut] = []


class MockClockOut(BaseModel):
    """The server's answer to "how long have I got" — never the browser's.

    A countdown on screen is a display of this. `AV-116` puts the clock on the
    server, so the page asks and shows; it does not decide.
    """

    opened_at: datetime
    # Both null when the tutor set no duration. An untimed mock is a normal
    # thing to set, and absent is shown as absent rather than as zero
    # (`PROD-2`, `UX-19`).
    due_at: datetime | None = None
    seconds_remaining: int | None = None
    # True once the time is up. It never blocks a submission — it labels one.
    overdue: bool = False


class MockSubmissionOut(BaseModel):
    submission_id: int
    mock_id: int
    title: str
    subject_name: str
    status: str
    submitted_at: datetime
    # How long the sitting actually took, measured by the server from when this
    # student first opened the paper. **Not self-declared** — the past-paper
    # `timed`/`time_taken_minutes` pair is, and the two must never be shown
    # under the same label (`PROD-8`, `UX-20`). Null when nothing measured it:
    # a submission that predates the clock, or one made without opening through
    # the API.
    measured_minutes: int | None = None
    # Whether it arrived after time was up. Recorded, never enforced.
    submitted_late: bool = False
    # Null until the submission has settled.
    raw_marks: int | None = None
    max_marks: int | None = None
