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
    # Readiness band ("on_track" | "needs_attention" | "at_risk") derived from
    # the predicted grade's position in the subject's boundary list — the one
    # source of the colour every surface shows (UX-28). None when there is no
    # grade or no boundaries, so an absent band renders as absent (PROD-2).
    status: str | None = None
    # The plain mean of marked work, mapped through the same boundaries as the
    # predicted grade above. Backward-looking, where predicted_grade is
    # forward-looking; the gap between them is what the surfaces explain
    # (experience-design.md §3.3). None when nothing has been marked yet —
    # never 0 (PROD-2). marked_piece_count says what the value came from
    # (PROD-1) and is 0 exactly when averaging_score is None.
    averaging_score: float | None = None
    averaging_grade: str | None = None
    marked_piece_count: int = 0
    # Direction of travel over the trend series: "up" | "flat" | "down", or
    # None when there is too little history to say (UX-31). None renders as no
    # arrow — a "→" would claim a movement that was never measured (PROD-2).
    direction: str | None = None
    topics: list[TopicReadinessOut]
    weak_topics: list[WeakTopic]
    # Which engine produced this. "v2" is the system of record; "v1" means no
    # v2 snapshot exists yet for this subject and the legacy engine answered.
    engine: str = "v2"
    # A recompute is queued or running: the score below is the last known one,
    # not the current one. The UI should say so rather than imply it is fresh.
    is_updating: bool = False
    computed_at: datetime | None = None
    # v2 only: the AI's explanation of the score and what to revise next.
    rationale: str | None = None
    recommended_revision: str | None = None


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


# ---- Readiness v2 weights (per factor, per organization) ----


class ReadinessWeightsOut(BaseModel):
    weight_topic_mastery: float
    weight_past_paper_performance: float
    weight_homework_performance: float
    weight_assessment_performance: float
    weight_syllabus_coverage: float
    weight_mistake_analysis: float
    weight_consistency: float
    half_life_days: float


class ReadinessWeightsUpdate(BaseModel):
    weight_topic_mastery: float = Field(ge=0, le=3)
    weight_past_paper_performance: float = Field(ge=0, le=3)
    weight_homework_performance: float = Field(ge=0, le=3)
    weight_assessment_performance: float = Field(ge=0, le=3)
    weight_syllabus_coverage: float = Field(ge=0, le=3)
    weight_mistake_analysis: float = Field(ge=0, le=3)
    weight_consistency: float = Field(ge=0, le=3)
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
