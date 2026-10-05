import type { ReadinessStatus } from "../components/ui";

/** One row of the Readiness table. `status` is the band the backend derived from
    the grade's boundary position (UX-28) and is null when there is none — a
    learner with a score but no boundaries is shown with the score only, never
    given a band computed here (PROD-2). */
export interface LearnerRow {
  student_id: number;
  student_name: string;
  subject_name: string;
  score: number;
  status: ReadinessStatus | null;
  predicted_grade?: string | null;
  group_id: number;
  group_name: string;
}

const BANDS: readonly string[] = ["on_track", "needs_attention", "at_risk"];

/** The wire types a status as a plain string (and adds "not_enough_data"); this
    narrows it to a band, or null. It checks membership — it never derives a
    band from a score. */
export function bandOf(status: string | null | undefined): ReadinessStatus | null {
  return status != null && BANDS.includes(status) ? (status as ReadinessStatus) : null;
}

export function greetingFor(hour: number): string {
  if (hour < 12) return "Good morning";
  if (hour < 18) return "Good afternoon";
  return "Good evening";
}
