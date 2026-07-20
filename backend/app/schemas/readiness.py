from datetime import date, datetime

from pydantic import BaseModel, Field


class TopicReadinessOut(BaseModel):
    topic_id: int
    topic_code: str
    topic_title: str
    score: float
    confidence: str
    evidence_count: int


class WeakTopic(BaseModel):
    topic_id: int
    topic_code: str
    topic_title: str
    score: float


class SubjectReadiness(BaseModel):
    subject_id: int
    subject_name: str
    exam_board: str
    grade_scale: str
    score: float | None  # None when there is no confident evidence yet
    predicted_grade: str | None
    topics: list[TopicReadinessOut]
    weak_topics: list[WeakTopic]


class EvidenceItem(BaseModel):
    source_type: str
    score_pct: float
    max_marks: int
    occurred_at: datetime
    label: str | None


class TopicEvidence(BaseModel):
    topic_id: int
    topic_code: str
    topic_title: str
    score: float
    confidence: str
    evidence: list[EvidenceItem]


class TrendPoint(BaseModel):
    recorded_at: datetime
    score: float


class SubjectTrend(BaseModel):
    subject_id: int
    subject_name: str
    points: list[TrendPoint]


class StudentReadinessSummary(BaseModel):
    student_id: int
    student_name: str
    subjects: list[SubjectReadiness]


# ---- Observations ----


class ObservationCreate(BaseModel):
    student_id: int
    topic_id: int | None = None
    comment: str = Field(min_length=1)
    rating: int | None = Field(default=None, ge=0, le=100)


class ObservationOut(BaseModel):
    id: int
    student_id: int
    topic_id: int | None
    comment: str
    rating: int | None
    created_at: datetime


# ---- Assessments (mocks / tests) ----


class AssessmentScoreIn(BaseModel):
    student_id: int
    topic_id: int | None = None
    marks: int = Field(ge=0)
    max_marks: int = Field(ge=1)


class AssessmentCreate(BaseModel):
    subject_id: int
    title: str = Field(min_length=1, max_length=255)
    type: str = Field(default="mock", pattern="^(mock|test)$")
    date: date
    scores: list[AssessmentScoreIn] = []


class AssessmentOut(BaseModel):
    id: int
    subject_id: int
    title: str
    type: str
    date: date
    score_count: int


class MyAssessmentScore(BaseModel):
    assessment_id: int
    title: str
    type: str
    date: date
    subject_id: int
    subject_name: str
    topic_id: int | None
    topic_title: str | None
    marks: int
    max_marks: int
    pct: float


# ---- Tutor preferences (readiness weights) ----


class PreferencesOut(BaseModel):
    weight_mock: float
    weight_homework: float
    weight_quiz: float
    weight_observation: float
    half_life_days: float


class PreferencesUpdate(BaseModel):
    weight_mock: float = Field(ge=0, le=3)
    weight_homework: float = Field(ge=0, le=3)
    weight_quiz: float = Field(ge=0, le=3)
    weight_observation: float = Field(ge=0, le=3)
    half_life_days: float = Field(ge=7, le=365)


# ---- Tutor analytics ----


class WeakStudent(BaseModel):
    student_id: int
    student_name: str
    subject_name: str
    score: float


class TopicHeat(BaseModel):
    topic_code: str
    topic_title: str
    avg_score: float
    student_count: int


class AgreementStats(BaseModel):
    total_marked_questions: int
    ai_agreed: int
    agreement_rate: float | None


class TutorAnalytics(BaseModel):
    weak_students: list[WeakStudent]
    weak_topics: list[TopicHeat]
    agreement: AgreementStats
