from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.groups import TopicOut


class ClassifiedOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    subject_id: int
    title: str
    file_name: str
    mark_scheme_name: str | None


class AssignmentCreate(BaseModel):
    group_id: int
    # The lesson this homework was assigned from, if any.
    lesson_id: int | None = None
    # Omit to create an assignment without a question booklet; the tutor
    # types the question list directly instead.
    classified_id: int | None = None
    title: str = Field(min_length=1, max_length=255)
    instructions: str | None = None
    due_at: datetime | None = None
    question_range: str | None = Field(default=None, max_length=128)


class QuestionIn(BaseModel):
    number: str = Field(min_length=1, max_length=16)
    text_summary: str
    max_marks: int = Field(ge=1, le=200)
    has_mark_scheme: bool
    topic_ids: list[int] = []


class QuestionOut(BaseModel):
    id: int
    number: str
    text_summary: str
    max_marks: int
    has_mark_scheme: bool
    topics: list[TopicOut]


class AssignmentOut(BaseModel):
    id: int
    group_id: int
    title: str
    status: str
    due_at: datetime | None
    question_count: int
    total_marks: int
    submission_count: int = 0


class AssignmentDetail(BaseModel):
    id: int
    group_id: int
    lesson_id: int | None
    classified_id: int | None
    title: str
    instructions: str | None
    due_at: datetime | None
    question_range: str | None
    status: str
    extraction_error: str | None
    questions: list[QuestionOut]


class AssignmentAttention(BaseModel):
    assignment_id: int
    assignment_title: str
    reason: str
    detail: str | None
    submission_id: int | None
    student_name: str | None


class StudentAssignment(BaseModel):
    id: int
    title: str
    instructions: str | None
    due_at: datetime | None
    subject_name: str
    group_name: str
    question_count: int
    total_marks: int
    submission_status: str | None
    my_total: int | None = None
    # When this piece was marked. The student's home groups recent results under
    # YOU DID, and without a date the only honest wording is "at some point" —
    # which is not a thing worth saying. None until the marks are settled.
    finalized_at: datetime | None = None
    # Whether this student's mark was the best in their class on this piece.
    # A boolean about the reader and nothing else: no classmate's mark, count or
    # identity is transmitted, and it is shown only to the student it is about
    # (experience-design §5.1). False whenever there is nothing to compare
    # against, so the absence of a comparison never reads as a bad result.
    highest_in_class: bool = False


class MarkRow(BaseModel):
    question_id: int
    number: str
    text_summary: str
    max_marks: int
    has_mark_scheme: bool
    ai_transcription: str | None
    ai_marks: int | None
    ai_feedback: str | None
    ai_confidence: str | None
    final_marks: int | None
    final_feedback: str | None
    overridden: bool
    # Why this row is (or isn't) in the tutor's review queue.
    needs_review: bool = False
    auto_finalized: bool = False
    remark_requested: bool = False
    remark_reason: str | None = None


class SubmissionFileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    mime: str
    position: int


class SubmissionSummary(BaseModel):
    id: int
    student_id: int
    student_name: str
    status: str
    submitted_at: datetime
    total_final: int | None
    total_max: int


class SubmissionDetail(BaseModel):
    id: int
    # Exactly one is set: homework or a past paper.
    assignment_id: int | None
    past_paper_id: int | None = None
    assignment_title: str
    student_id: int
    student_name: str
    status: str
    ai_error: str | None
    submitted_at: datetime
    files: list[SubmissionFileOut]
    marks: list[MarkRow]


class MarkUpdate(BaseModel):
    question_id: int
    final_marks: int | None = Field(default=None, ge=0)
    final_feedback: str | None = None


class StudentMarkRow(BaseModel):
    # Null only for the legacy no-submission shape; needed so a student can
    # ask for a specific question to be looked at again.
    question_id: int | None = None
    number: str
    text_summary: str
    max_marks: int
    final_marks: int | None
    final_feedback: str | None
    # "open" | "resolved" | None — lets the UI disable "Request remark" once
    # this question has already been contested.
    remark_status: str | None = None


class StudentSubmissionView(BaseModel):
    submission_id: int | None = None
    status: str
    submitted_at: datetime | None
    finalized_at: datetime | None
    total: int | None
    total_max: int
    marks: list[StudentMarkRow]


class ReviewQueueItem(BaseModel):
    """One submission waiting on the tutor — the whole marking workload."""

    submission_id: int
    # Exactly one is set: the work is homework or a past paper.
    assignment_id: int | None
    past_paper_id: int | None = None
    assignment_title: str
    student_id: int
    student_name: str
    submitted_at: datetime
    # Questions the AI flagged as uncertain.
    unsure_count: int
    # Questions a student has asked to have looked at again.
    remark_request_count: int


class MarkHistoryEntry(BaseModel):
    old_marks: int | None
    new_marks: int | None
    changed_by_name: str
    reason: str | None
    created_at: datetime


class RemarkRequestCreate(BaseModel):
    reason: str | None = None


class RemarkRequestOut(BaseModel):
    id: int
    question_id: int
    status: str
    reason: str | None
    created_at: datetime
