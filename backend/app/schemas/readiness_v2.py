from datetime import datetime

from pydantic import BaseModel


class FactorEvaluationOut(BaseModel):
    factor: str
    topic_id: int | None
    topic_title: str | None
    score: float | None
    confidence: str
    evidence_count: int
    detail: dict


class WeakTopicOut(BaseModel):
    topic_id: int
    topic_title: str | None
    reason: str


class ReadinessSnapshotOut(BaseModel):
    subject_id: int
    subject_name: str
    status: str
    score: float | None
    predicted_grade: str | None
    weak_topics: list[WeakTopicOut]
    rationale: str | None
    recommended_revision: str | None
    error: str | None
    created_at: datetime
    factors: list[FactorEvaluationOut]


class StudentReadinessV2Summary(BaseModel):
    student_id: int
    student_name: str
    subjects: list[ReadinessSnapshotOut]
