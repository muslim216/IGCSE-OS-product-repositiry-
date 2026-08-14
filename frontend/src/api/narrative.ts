import { api } from "./client";

/**
 * The stored narrative — a precomputed paragraph read from the database, not a
 * live model call, so a surface renders its primary content on open (spec §8).
 *
 * `text` is null, never "", when nothing has been generated yet: the surface
 * states the absence in words rather than rendering an empty panel (PROD-2,
 * UX-19). There are no review fields, because there is no review step (D2).
 */
export interface Narrative {
  text: string | null;
  generated_at: string | null;
  prompt_version: string | null;
}

/** The class paragraph, for the tutor's home and class page. */
export const groupNarrative = (groupId: number) =>
  api<Narrative>(`/api/v1/groups/${groupId}/narrative`);

/** The paragraph about one child, for that child's parent (and their tutor). */
export const studentNarrative = (studentId: number) =>
  api<Narrative>(`/api/v1/students/${studentId}/narrative`);
