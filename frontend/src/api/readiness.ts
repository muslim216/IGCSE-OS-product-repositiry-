import type { ReadinessStatus } from "../components/ui";
import { api } from "./client";

export interface TopicReadiness {
  topic_id: number;
  topic_code: string;
  topic_title: string;
  score: number;
  confidence: string;
  evidence_count: number;
}

export interface WeakTopic {
  topic_id: number;
  topic_code: string;
  topic_title: string;
  score: number;
}

export interface SubjectReadiness {
  subject_id: number;
  subject_name: string;
  exam_board: string;
  grade_scale: string;
  score: number | null;
  predicted_grade: string | null;
  /** Readiness band from the predicted grade's boundary position — the one
      source of the colour surfaces show. null when there is no grade or no
      boundaries, and is then rendered as absent, never a defaulted colour. */
  status: ReadinessStatus | null;
  /** The plain mean of marked work, mapped through the same boundaries as
      predicted_grade — backward-looking where the prediction looks forward.
      null when nothing is marked yet, never 0. */
  averaging_score: number | null;
  averaging_grade: string | null;
  /** How many marked pieces the averaging value came from; 0 exactly when
      averaging_score is null. */
  marked_piece_count: number;
  /** Direction of travel over the trend series. null means too little history
      to say — render no arrow at all, never "→", which would be a claim. */
  direction: "up" | "flat" | "down" | null;
  /** Net movement over the last 30 days, from the same series as `direction` —
      so a surface can never print an up arrow beside a negative number. null
      when the series does not span the window; never 0 standing in for that. */
  month_delta: number | null;
  /** Coverage: topics carrying evidence over topics that exist. The pair is
      what lets a surface show `9/11` rather than implying the score speaks
      for the whole subject. */
  topics_with_evidence: number;
  topic_count: number;
  topics: TopicReadiness[];
  weak_topics: WeakTopic[];
  /** "v2" is the system of record; "v1" means no v2 snapshot exists yet. */
  engine: string;
  /** A recompute is queued or running — the score shown is the last known one. */
  is_updating: boolean;
  computed_at: string | null;
  rationale: string | null;
  recommended_revision: string | null;
}

export interface ReadinessSummary {
  student_id: number;
  student_name: string;
  subjects: SubjectReadiness[];
}

export interface EvidenceItem {
  source_type: string;
  score_pct: number;
  max_marks: number;
  occurred_at: string;
  label: string | null;
}

export interface TopicEvidence {
  topic_id: number;
  topic_code: string;
  topic_title: string;
  score: number;
  confidence: string;
  evidence: EvidenceItem[];
}

export interface TrendPoint {
  recorded_at: string;
  score: number;
}

export interface SubjectTrend {
  subject_id: number;
  subject_name: string;
  points: TrendPoint[];
}

export interface WeakStudent {
  student_id: number;
  student_name: string;
  subject_name: string;
  score: number;
}

export interface TopicHeat {
  topic_code: string;
  topic_title: string;
  avg_score: number;
  student_count: number;
}

export interface AgreementStats {
  total_marked_questions: number;
  ai_agreed: number;
  agreement_rate: number | null;
}

export interface TutorAnalytics {
  weak_students: WeakStudent[];
  weak_topics: TopicHeat[];
  agreement: AgreementStats;
}

export interface AssessmentScoreIn {
  student_id: number;
  topic_id: number | null;
  marks: number;
  max_marks: number;
}

export interface Assessment {
  id: number;
  subject_id: number;
  title: string;
  type: string;
  date: string;
  score_count: number;
}

export const myReadiness = () => api<ReadinessSummary>("/api/v1/readiness/me");
export const studentReadiness = (studentId: number) =>
  api<ReadinessSummary>(`/api/v1/readiness/students/${studentId}`);
export const topicEvidence = (studentId: number, topicId: number) =>
  api<TopicEvidence>(`/api/v1/readiness/students/${studentId}/topics/${topicId}/evidence`);
export const studentTrend = (studentId: number) =>
  api<SubjectTrend[]>(`/api/v1/readiness/students/${studentId}/trend`);
export const groupAnalytics = (groupId: number) =>
  api<TutorAnalytics>(`/api/v1/analytics/groups/${groupId}`);

export const listAssessments = (subjectId?: number) =>
  api<Assessment[]>(`/api/v1/assessments${subjectId ? `?subject_id=${subjectId}` : ""}`);

export const createAssessment = (payload: {
  subject_id: number;
  title: string;
  type: string;
  date: string;
  scores: AssessmentScoreIn[];
}) => api<Assessment>("/api/v1/assessments", { method: "POST", body: JSON.stringify(payload) });

export interface MyAssessmentScore {
  assessment_id: number;
  title: string;
  type: string;
  date: string;
  subject_id: number;
  subject_name: string;
  topic_id: number | null;
  topic_title: string | null;
  marks: number;
  max_marks: number;
  pct: number;
}

export const myAssessmentScores = () => api<MyAssessmentScore[]>("/api/v1/me/assessments");

export interface Preferences {
  weight_mock: number;
  weight_homework: number;
  weight_quiz: number;
  weight_observation: number;
  half_life_days: number;
}

export const getPreferences = () => api<Preferences>("/api/v1/me/preferences");

/** Readiness v2 weights: one per factor, per organization. */
export interface ReadinessWeights {
  weight_topic_mastery: number;
  weight_past_paper_performance: number;
  weight_homework_performance: number;
  weight_assessment_performance: number;
  weight_syllabus_coverage: number;
  weight_mistake_analysis: number;
  weight_consistency: number;
  half_life_days: number;
}

export const getReadinessWeights = () => api<ReadinessWeights>("/api/v1/readiness/weights");
export const updateReadinessWeights = (payload: ReadinessWeights) =>
  api<ReadinessWeights>("/api/v1/readiness/weights", {
    method: "PUT",
    body: JSON.stringify(payload),
  });
export const updatePreferences = (payload: Preferences) =>
  api<Preferences>("/api/v1/me/preferences", { method: "PUT", body: JSON.stringify(payload) });

/** A tutor's own starting estimate for a student, per topic. Self-declared: it
    is stored as `tutor_estimate` evidence, labelled as such wherever it is
    shown, and loses weight as marked work arrives (PROD-8, spec §7.3). */
export const seedStudentReadiness = (
  studentId: number,
  topics: { topic_id: number; score_pct: number }[],
) =>
  api<{ seeded: number }>(`/api/v1/students/${studentId}/seed-readiness`, {
    method: "POST",
    body: JSON.stringify({ topics }),
  });

export const createObservation = (payload: {
  student_id: number;
  topic_id: number | null;
  comment: string;
  rating: number | null;
}) => api<unknown>("/api/v1/observations", { method: "POST", body: JSON.stringify(payload) });
