from datetime import datetime

from pydantic import BaseModel, Field


class ReportGenerate(BaseModel):
    student_id: int
    audience: str = Field(pattern="^(student|tutor|parent)$")
    subject_id: int | None = None


class ReportOut(BaseModel):
    id: int
    student_id: int
    subject_id: int | None
    audience: str
    status: str
    title: str
    created_at: datetime
    generated_at: datetime | None


class ReportDetail(ReportOut):
    content: str | None
    error: str | None
