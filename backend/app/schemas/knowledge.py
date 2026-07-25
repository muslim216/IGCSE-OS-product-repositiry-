from datetime import datetime

from pydantic import BaseModel, Field

from app.models.knowledge import KnowledgeEntryKind


class KnowledgeEntryCreate(BaseModel):
    kind: KnowledgeEntryKind
    title: str = Field(min_length=1, max_length=255)
    body: str = Field(min_length=1)
    subject_id: int | None = None


class KnowledgeEntryUpdate(BaseModel):
    kind: KnowledgeEntryKind
    title: str = Field(min_length=1, max_length=255)
    body: str = Field(min_length=1)
    subject_id: int | None = None


class KnowledgeEntryOut(BaseModel):
    id: int
    kind: str
    title: str
    body: str
    subject_id: int | None
    created_at: datetime
