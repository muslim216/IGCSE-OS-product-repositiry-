from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class GradeBoundaryIn(BaseModel):
    grade: str
    min: int


class SyllabusTopicIn(BaseModel):
    code: str
    title: str
    weight: float = 1.0
    children: list[SyllabusTopicIn] = []


class SyllabusDraft(BaseModel):
    exam_board: str
    code: str
    name: str
    grade_scale: str
    grade_boundaries: list[GradeBoundaryIn]
    topics: list[SyllabusTopicIn]


class SyllabusUploadOut(BaseModel):
    id: int
    title: str
    file_name: str
    status: str
    error: str | None
    subject_id: int | None
    created_at: datetime


class SyllabusUploadDetail(SyllabusUploadOut):
    draft: SyllabusDraft | None
