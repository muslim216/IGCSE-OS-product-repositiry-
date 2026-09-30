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
    #: Whether the tutor's *current* config counts this factor (task 5.4a) —
    #: read-time config, not what applied when the run was synthesized. A
    #: config save enqueues a recompute, so the two converge.
    enabled: bool


class ChapterReadinessOut(BaseModel):
    """A chapter's Topic Mastery rolled up from its topics in the same run
    (task 5.2, AV-9): a mean weighted by evidence count, `score` null when no
    topic beneath has any (`PROD-2`). API only for now (decision 7)."""

    chapter_id: int
    title: str
    score: float | None
    confidence: str
    evidence_count: int
    detail: dict


class WeakTopicOut(BaseModel):
    """Derived from this run's Topic Mastery rows and the tutor's current
    threshold (task 5.6) — the score is the reason; the AI no longer writes one."""

    topic_id: int
    topic_title: str | None
    score: float


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
    #: In teaching order. Empty for a run from before task 5.2.
    chapters: list[ChapterReadinessOut]


class StudentReadinessV2Summary(BaseModel):
    student_id: int
    student_name: str
    subjects: list[ReadinessSnapshotOut]
