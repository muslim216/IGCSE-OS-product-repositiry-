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
    # `title` is what extraction actually read off the document, and is null
    # until it has run. `display_title` is that with the "Untitled paper"
    # fallback applied.
    #
    # Both are on the wire deliberately. A single non-null `title` carrying the
    # fallback would make "not read yet" indistinguishable from "a paper
    # genuinely called that" — and task 3.5's review screen is a round-trip
    # form, so an unedited row would write the literal string "Untitled paper"
    # back into the column, which is the fabricated value `PROD-2` exists to
    # prevent. Anything that only displays reads `display_title`; anything that
    # edits reads `title`.
    title: str | None
    display_title: str
    # AI-filled alongside `title`; the tutor no longer types either, so both
    # are absent on a paper whose extraction hasn't run yet.
    session_label: str | None
    paper_number: str | None
    total_marks: int | None
    duration_minutes: int | None
    booklet_name: str | None
    # Present for tutors only — students must never see the mark scheme.
    mark_scheme_name: str | None = None
    extraction_error: str | None = None
    question_count: int = 0


class PastPaperDetail(PastPaperOut):
    questions: list[PastPaperQuestionOut] = []


class PastPaperAttemptOut(BaseModel):
    submission_id: int
    past_paper_id: int
    title: str
    session_label: str | None
    paper_number: str | None
    subject_name: str
    status: str
    timed: bool
    time_taken_minutes: int | None
    attempted_at: date | None
    submitted_at: datetime
    # Null until the attempt has settled.
    raw_marks: int | None = None
    max_marks: int | None = None
