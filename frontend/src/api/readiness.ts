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
  topics: TopicReadiness[];
  weak_topics: WeakTopic[];
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
}) =>
  api<Assessment>("/api/v1/assessments", { method: "POST", body: JSON.stringify(payload) });

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
export const updatePreferences = (payload: Preferences) =>
  api<Preferences>("/api/v1/me/preferences", { method: "PUT", body: JSON.stringify(payload) });

export const createObservation = (payload: {
  student_id: number;
  topic_id: number | null;
  comment: string;
  rating: number | null;
}) =>
  api<unknown>("/api/v1/observations", { method: "POST", body: JSON.stringify(payload) });
