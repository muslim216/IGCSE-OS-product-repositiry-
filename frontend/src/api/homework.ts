import { api, apiUrl, getStoredTokens, type Present } from "./client";
import type { components } from "./schema";

export type Classified = components["schemas"]["ClassifiedOut"];
export type Question = components["schemas"]["QuestionOut"];
export type QuestionIn = components["schemas"]["QuestionIn"];
export type Assignment = components["schemas"]["AssignmentOut"];
export type AssignmentDetail = components["schemas"]["AssignmentDetail"];

/**
 * The student's view of an assignment. Two fields carry usage rules the shape
 * alone does not (CODE-13):
 * - `is_open` — whether the assignment still accepts a submission. The list
 *   includes closed assignments (their marks stay in history), so a "Start"
 *   action must gate on this, not on submission status alone.
 * - `finalized_at` — when the marks were settled; null until then. The home
 *   uses it to tell recent results from everything ever marked, and cannot
 *   guess a date.
 * - `highest_in_class` — whether this student's mark was the best in their
 *   class on this piece. A boolean about the reader and nothing else: no
 *   classmate's mark, count or identity is sent, and it is shown only to the
 *   student it is about. False whenever there is nothing to compare against,
 *   so an absent comparison never reads as a bad result.
 */
export type StudentAssignment = components["schemas"]["StudentAssignment"];

/** `needs_review` is why this row is (or isn't) waiting on the tutor. */
export type MarkRow = components["schemas"]["MarkRow"];
export type ReviewQueueItem = components["schemas"]["ReviewQueueItem"];
export type MarkHistoryEntry = components["schemas"]["MarkHistoryEntry"];
export type RemarkRequestOut = components["schemas"]["RemarkRequestOut"];
export type SubmissionSummary = components["schemas"]["SubmissionSummary"];
export type SubmissionFileInfo = components["schemas"]["SubmissionFileOut"];

/** `assignment_id` and `past_paper_id` are polymorphic: exactly one is set —
    the work is homework or a past paper (never read the other unconditionally,
    API-20). */
export type SubmissionDetail = components["schemas"]["SubmissionDetail"];

/** `remark_status` is set once the student has asked for this mark to be looked
    at again. */
export type StudentMarkRow = Present<components["schemas"]["StudentMarkRow"]>;
export type StudentSubmissionView = Present<
  Omit<components["schemas"]["StudentSubmissionView"], "marks">
> & {
  marks: StudentMarkRow[];
};

export const listClassifieds = (subjectId?: number) =>
  api<Classified[]>(`/api/v1/classifieds${subjectId ? `?subject_id=${subjectId}` : ""}`);

export function uploadClassified(payload: {
  title: string;
  subject_id: number;
  file: File;
  mark_scheme: File | null;
}) {
  const form = new FormData();
  form.append("title", payload.title);
  form.append("subject_id", String(payload.subject_id));
  form.append("file", payload.file);
  if (payload.mark_scheme) form.append("mark_scheme", payload.mark_scheme);
  return api<Classified>("/api/v1/classifieds", { method: "POST", body: form });
}

/** One request: upload a paper and set it as homework. Only the group and the
    file are required — the title falls back to the file name server-side. */
export function uploadAssignment(payload: {
  group_id: number;
  file: File;
  mark_scheme?: File | null;
  title?: string;
  instructions?: string;
  due_at?: string | null;
  question_range?: string | null;
}) {
  const form = new FormData();
  form.append("group_id", String(payload.group_id));
  form.append("file", payload.file);
  if (payload.mark_scheme) form.append("mark_scheme", payload.mark_scheme);
  if (payload.title) form.append("title", payload.title);
  if (payload.instructions) form.append("instructions", payload.instructions);
  if (payload.due_at) form.append("due_at", payload.due_at);
  if (payload.question_range) form.append("question_range", payload.question_range);
  return api<AssignmentDetail>("/api/v1/assignments/upload", { method: "POST", body: form });
}

export const createAssignment = (payload: {
  group_id: number;
  classified_id?: number | null;
  title: string;
  instructions?: string;
  due_at?: string | null;
  question_range?: string | null;
}) =>
  api<AssignmentDetail>("/api/v1/assignments", {
    method: "POST",
    body: JSON.stringify(payload),
  });

export const listGroupAssignments = (groupId: number) =>
  api<Assignment[]>(`/api/v1/assignments/group/${groupId}`);
export const getAssignment = (id: number) => api<AssignmentDetail>(`/api/v1/assignments/${id}`);
export const replaceQuestions = (id: number, questions: QuestionIn[]) =>
  api<AssignmentDetail>(`/api/v1/assignments/${id}/questions`, {
    method: "PUT",
    body: JSON.stringify(questions),
  });
export const publishAssignment = (id: number) =>
  api<AssignmentDetail>(`/api/v1/assignments/${id}/publish`, { method: "POST" });
export const retryExtraction = (id: number) =>
  api<AssignmentDetail>(`/api/v1/assignments/${id}/retry-extraction`, { method: "POST" });

export type AssignmentAttention = components["schemas"]["AssignmentAttention"];

export const assignmentsNeedingAttention = () =>
  api<AssignmentAttention[]>("/api/v1/assignments/attention");

export const myAssignments = () => api<StudentAssignment[]>("/api/v1/me/assignments");
export const mySubmission = (assignmentId: number) =>
  api<StudentSubmissionView>(`/api/v1/assignments/${assignmentId}/my-submission`);

export function submitWork(assignmentId: number, files: File[]) {
  const form = new FormData();
  for (const f of files) form.append("files", f);
  return api<StudentSubmissionView>(`/api/v1/assignments/${assignmentId}/submissions`, {
    method: "POST",
    body: form,
  });
}

export const listSubmissions = (assignmentId: number) =>
  api<SubmissionSummary[]>(`/api/v1/assignments/${assignmentId}/submissions`);
export const getSubmission = (id: number) => api<SubmissionDetail>(`/api/v1/submissions/${id}`);
export const saveMarks = (
  id: number,
  marks: { question_id: number; final_marks: number | null; final_feedback: string | null }[],
) =>
  api<SubmissionDetail>(`/api/v1/submissions/${id}/marks`, {
    method: "PUT",
    body: JSON.stringify(marks),
  });
export const finalizeSubmission = (id: number) =>
  api<SubmissionDetail>(`/api/v1/submissions/${id}/finalize`, { method: "POST" });

/** Everything waiting on the tutor: AI-unsure marks and student remark requests. */
export const reviewQueue = () => api<ReviewQueueItem[]>("/api/v1/submissions/review-queue");

export const markHistory = (submissionId: number, questionId: number) =>
  api<MarkHistoryEntry[]>(`/api/v1/submissions/${submissionId}/marks/${questionId}/history`);

/** Student-initiated. Never re-marked by AI — it goes to the tutor's queue. */
export const requestRemark = (submissionId: number, questionId: number, reason: string) =>
  api<RemarkRequestOut>(
    `/api/v1/submissions/${submissionId}/questions/${questionId}/remark-request`,
    { method: "POST", body: JSON.stringify({ reason: reason || null }) },
  );

/** Fetch a protected file with auth and return an object URL for display. */
export async function fetchFileUrl(path: string): Promise<string> {
  const tokens = getStoredTokens();
  const resp = await fetch(apiUrl(path), {
    headers: tokens ? { Authorization: `Bearer ${tokens.access_token}` } : {},
  });
  if (!resp.ok) throw new Error(`Could not load file (${resp.status})`);
  return URL.createObjectURL(await resp.blob());
}

export const submissionFilePath = (submissionId: number, fileId: number) =>
  `/api/v1/submissions/${submissionId}/files/${fileId}`;
export const classifiedFilePath = (classifiedId: number) =>
  `/api/v1/classifieds/${classifiedId}/file`;
