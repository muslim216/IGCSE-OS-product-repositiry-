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

/** The student's own mistake pattern, one entry per subject they are enrolled
 *  in (4.5).
 *
 * Deliberately a different shape from `StudentMistakeRollup`: categories only,
 * no severity and no syllabus breakdown. Severity is an internal weighting
 * signal and reads as a verdict to the person who made the mistakes, so the
 * server does not send it rather than trusting a client not to render it.
 *
 * There is no student id to pass — the student is the token holder (`SEC-7`).
 * `analysed_questions === 0` means nobody has examined that subject's work,
 * which is not a clean record (`PROD-2`).
 */
export type MyMistakePattern = components["schemas"]["MyMistakePattern"];

export const myMistakes = () => api<MyMistakePattern[]>("/api/v1/me/mistakes");

/** A student in the tutor's cross-class list: who they are and which of the
 *  caller's classes they sit in. Nothing derived. */
export type TutorStudent = components["schemas"]["TutorStudentRow"];

/** Mirrors `STUDENT_LIST_LIMIT` in backend/app/services/tutor_lists.py: the most
 *  students `GET /students` returns, so a list this long may have been cut short. */
export const STUDENT_LIST_LIMIT = 500;

export const listMyStudents = () => api<TutorStudent[]>("/api/v1/students");
