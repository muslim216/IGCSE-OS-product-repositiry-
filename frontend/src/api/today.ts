import type { ReadinessStatus } from "../components/ui";
import type { UpcomingLesson } from "./groups";
import { api } from "./client";

/**
 * One class on the tutor's home strip.
 *
 * Every absent measurement is null, never 0 — a class with no confident evidence
 * renders as "not enough data yet", not an empty bar (PROD-2, UX-19). Coverage
 * arrives as a pair so the surface can say `9/11`: a status without coverage is
 * a claim about a class made from part of it.
 */
export interface ClassStripRow {
  group_id: number;
  name: string;
  subject_name: string;
  score: number | null;
  predicted_grade: string | null;
  /** Band from the predicted grade's boundary position, never a percentage
      threshold (UX-28). null when there is no grade or no boundaries. */
  status: ReadinessStatus | null;
  /** The subject has no boundaries in either source, so the surface offers
      "Set them →" rather than silently showing no grade. */
  boundaries_missing: boolean;
  member_count: number;
  students_with_evidence: number;
  awaiting_review_count: number;
}

/**
 * Everything the tutor's home needs, in one response. Replaces a per-class
 * fan-out that itself looped per learner server-side (PERF-1).
 */
export interface TodayView {
  /** Exceptions first: at risk, then needs attention, then healthy. */
  classes: ClassStripRow[];
  /** Today's lessons in the organization's timezone, not the server's. */
  lessons: UpcomingLesson[];
  review_count: number;
  class_count: number;
  joined_student_count: number;
  classes_with_evidence: number;
}

export const todayView = () => api<TodayView>("/api/v1/today");

/** One learner on the class page. `direction` is what NEEDS YOU selects on —
    null means too little history to say, and renders as no arrow at all. */
export interface ClassLearnerRow {
  student_id: number;
  student_name: string;
  score: number | null;
  predicted_grade: string | null;
  status: ReadinessStatus | null;
  direction: "up" | "flat" | "down" | null;
}

export interface ClassWeakTopic {
  topic_code: string;
  topic_title: string;
  avg_score: number;
  student_count: number;
}

export interface ClassOverview {
  group_id: number;
  name: string;
  subject_name: string;
  score: number | null;
  predicted_grade: string | null;
  status: ReadinessStatus | null;
  boundaries_missing: boolean;
  member_count: number;
  students_with_evidence: number;
  /** Selected on direction, not level: declining learners the tutor can help. */
  needs_you: ClassLearnerRow[];
  learners: ClassLearnerRow[];
  weak_topics: ClassWeakTopic[];
}

export const classOverview = (groupId: number) =>
  api<ClassOverview>(`/api/v1/today/classes/${groupId}`);
