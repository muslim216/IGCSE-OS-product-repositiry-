from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from app.models import SubjectLevel


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
    # Optional in the draft, required to apply. The extractor does not propose a
    # level yet (task 2.3), and AV-7 forbids assuming an IGCSE-shaped world, so
    # the tutor states it during review rather than the server guessing. Apply
    # refuses a draft that still has none.
    level: SubjectLevel | None = None
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
