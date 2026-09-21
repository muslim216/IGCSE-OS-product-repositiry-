import { api } from "./client";
import type { components } from "./schema";

// FE-4: aliases of the generated schema, never hand-written interfaces — a
// rename on the server becomes a compile error here rather than a silent
// divergence (RISK-6).
export type StudentMistakeRollup = components["schemas"]["StudentMistakeRollup"];
export type MistakeTally = components["schemas"]["MistakeTally"];

/** One student's tagged mistakes across one subject, all time (4.4).
 *
 * `analysed_questions` is the denominator and zero means *no data*, not a
 * clean record. `total` is the only subject figure: the per-topic and
 * per-chapter tallies count a multi-topic mistake once under each topic it
 * touches (decision 11), so they must never be summed.
 */
export const studentMistakes = (studentId: number, subjectId: number) =>
  api<StudentMistakeRollup>(`/api/v1/students/${studentId}/mistakes?subject_id=${subjectId}`);
