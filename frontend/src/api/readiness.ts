import type { ReadinessStatus } from "../components/ui";
import type { components } from "./schema";
import { api, type Present } from "./client";

export type TopicReadiness = components["schemas"]["TopicReadinessOut"];

export type WeakTopic = components["schemas"]["WeakTopic"];

/**
 * One subject's readiness. Anchored to the generated schema; two fields keep a
 * frontend refinement of a plain-`str` OpenAPI field (CODE-13):
 * - `status` — the readiness band from the predicted grade's boundary position,
 *   the one source of the colour surfaces show. null when there is no grade or
 *   no boundaries, and is then rendered as absent, never a defaulted colour.
 * - `direction` — direction of travel over the trend series. null means too
 *   little history to say — render no arrow at all, never "→", which would be a
 *   claim.
 *
 * The other absence-bearing fields keep their generated types: `averaging_score`
 * is the plain mean of marked work (null when nothing is marked yet, never 0);
 * `month_delta` is net movement over the last 30 days from the same series as
 * `direction`; `topics_with_evidence`/`topic_count` are the coverage pair that
 * lets a surface show `9/11`; `engine` is "v2" (system of record) or "v1" (no
 * v2 snapshot yet); `is_updating` means a recompute is queued or running and the
 * score shown is the last known one.
 */
export type SubjectReadiness = Present<
  Omit<components["schemas"]["SubjectReadiness"], "status" | "direction">
> & {
  status: ReadinessStatus | null;
  direction: "up" | "flat" | "down" | null;
};

export type ReadinessSummary = Omit<
  components["schemas"]["StudentReadinessSummary"],
  "subjects"
> & {
  subjects: SubjectReadiness[];
};

export type EvidenceItem = components["schemas"]["EvidenceItem"];

export type TopicEvidence = components["schemas"]["TopicEvidence"];

export type TrendPoint = components["schemas"]["TrendPoint"];

export type SubjectTrend = components["schemas"]["SubjectTrend"];

export type WeakStudent = components["schemas"]["WeakStudent"];

export type TopicHeat = components["schemas"]["TopicHeat"];

export type AgreementStats = components["schemas"]["AgreementStats"];

export type TutorAnalytics = components["schemas"]["TutorAnalytics"];

export type AssessmentScoreIn = components["schemas"]["AssessmentScoreIn"];

export type Assessment = components["schemas"]["AssessmentOut"];

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

export type MyAssessmentScore = components["schemas"]["MyAssessmentScore"];

export const myAssessmentScores = () => api<MyAssessmentScore[]>("/api/v1/me/assessments");

export type Preferences = components["schemas"]["PreferencesOut"];

export const getPreferences = () => api<Preferences>("/api/v1/me/preferences");

/** Readiness v2 weights: one per factor, per organization. */
export type ReadinessWeights = components["schemas"]["ReadinessWeightsOut"];

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
