import { api } from "./client";

/* The improvement tab's contract, mirroring backend/app/schemas/improvement.py.
 *
 * Every field here is the reader's own datum or a count. There is no field that
 * can hold a classmate's score, grade, delta, name or identity — that is the
 * design, not an omission, and adding one reopens the de-anonymisation vectors
 * documented in backend/app/services/improvement.py. */

export interface ImprovementPeriod {
  label: string;
  /** The reader's own movement. null when their history does not span the
      window — stated as absent, never shown as 0. */
  delta: number | null;
  /** The reader's own placing, or null when a gate is not met. */
  rank: number | null;
  ranked_count: number;
  /** Show "in the second half" rather than a number: the bottom half, or a tie
      spanning the halfway line. */
  banded: boolean;
}

export interface FocusTopic {
  topic_code: string;
  topic_title: string;
  score: number | null;
}

export interface SubjectImprovement {
  subject_id: number;
  subject_name: string;
  window_days: number;
  member_count: number;
  periods: ImprovementPeriod[];
  focus: FocusTopic[];
}

export const myImprovement = () => api<SubjectImprovement[]>("/api/v1/improvement/me");
