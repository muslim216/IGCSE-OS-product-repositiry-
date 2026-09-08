from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from app.models import SubjectLevel


class SyllabusTopicIn(BaseModel):
    code: str
    title: str
    weight: float = 1.0
    children: list[SyllabusTopicIn] = []


class SyllabusChapterIn(BaseModel):
    code: str
    title: str
    topics: list[SyllabusTopicIn] = []


class SyllabusDraft(BaseModel):
    exam_board: str
    code: str
    name: str
    # Optional in the draft, required to apply. The extractor proposes a level
    # only where the document states one (task 2.3), and AV-7 forbids assuming an
    # IGCSE-shaped world, so the tutor states it during review otherwise. Apply
    # refuses a draft that still has none.
    level: SubjectLevel | None = None
    grade_scale: str
    # Chapter-first since task 2.3 (AV-9). Grade boundaries are no longer part of
    # the draft — a syllabus document does not publish them, so they are
    # tutor-entered (task 2.4, AV-11).
    chapters: list[SyllabusChapterIn]


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
