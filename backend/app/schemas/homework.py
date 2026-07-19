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
    classified_id: int
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
    classified_id: int
    title: str
    instructions: str | None
    due_at: datetime | None
    question_range: str | None
    status: str
    extraction_error: str | None
    questions: list[QuestionOut]


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
    assignment_id: int
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
    number: str
    text_summary: str
    max_marks: int
    final_marks: int | None
    final_feedback: str | None


class StudentSubmissionView(BaseModel):
    status: str
    submitted_at: datetime | None
    finalized_at: datetime | None
    total: int | None
    total_max: int
    marks: list[StudentMarkRow]
