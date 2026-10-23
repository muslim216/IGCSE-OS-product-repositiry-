import unicodedata
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.schemas.readiness import SubjectReadiness


class StudentProfileUpdate(BaseModel):
    school: str | None = Field(default=None, max_length=255)
    year_group: str | None = Field(default=None, max_length=64)
    parent_name: str | None = Field(default=None, max_length=128)
    parent_email: str | None = Field(default=None, max_length=255)
    parent_phone: str | None = Field(default=None, max_length=64)


class StudentRename(BaseModel):
    name: str = Field(min_length=1, max_length=128)

    @field_validator("name", mode="before")
    @classmethod
    def _clean(cls, v):
        if not isinstance(v, str):
            return v
        # Control and format characters (newlines, zero-width, bidi overrides)
        # have no place in a name that is printed into reports and messages.
        if any(unicodedata.category(c).startswith("C") for c in v):
            raise ValueError("Names can't contain control or invisible characters.")
        return " ".join(v.split())


class StudentRenamed(BaseModel):
    id: int
    name: str


class StudentProfileOut(BaseModel):
    school: str | None
    year_group: str | None
    parent_name: str | None
    parent_email: str | None
    parent_phone: str | None
    updated_at: datetime


class StudentSubjectCreate(BaseModel):
    subject_id: int
    target_grade: str | None = Field(default=None, max_length=16)


class StudentSubjectUpdate(BaseModel):
    target_grade: str | None = Field(default=None, max_length=16)


class StudentSubjectOut(BaseModel):
    subject_id: int
    subject_name: str
    exam_board: str
    target_grade: str | None


class TutorNoteCreate(BaseModel):
    body: str = Field(min_length=1)


class TutorNoteOut(BaseModel):
    id: int
    tutor_id: int
    tutor_name: str
    body: str
    created_at: datetime


class ParentCommunicationCreate(BaseModel):
    body: str = Field(min_length=1)


class ParentCommunicationOut(BaseModel):
    id: int
    tutor_id: int
    tutor_name: str
    body: str
    created_at: datetime


class CrmHomeworkItem(BaseModel):
    assignment_id: int
    title: str
    status: str
    due_at: datetime | None
    submission_status: str | None
    total_final: int | None
    total_max: int


class StudentCrmOut(BaseModel):
    """The student's full academic record, as the CRM page reads it."""

    student_id: int
    student_name: str
    profile: StudentProfileOut | None
    enrollments: list[StudentSubjectOut]
    readiness: list[SubjectReadiness]
    homework: list[CrmHomeworkItem]
    notes: list[TutorNoteOut]
    communications: list[ParentCommunicationOut]
