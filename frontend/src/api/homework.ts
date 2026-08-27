import { api, apiUrl, getStoredTokens } from "./client";
import type { Topic } from "./syllabus";

export interface Classified {
  id: number;
  subject_id: number;
  title: string;
  file_name: string;
  mark_scheme_name: string | null;
}

export interface Question {
  id: number;
  number: string;
  text_summary: string;
  max_marks: number;
  has_mark_scheme: boolean;
  topics: Topic[];
}

export interface QuestionIn {
  number: string;
  text_summary: string;
  max_marks: number;
  has_mark_scheme: boolean;
  topic_ids: number[];
}

export interface Assignment {
  id: number;
  group_id: number;
  title: string;
  status: string;
  due_at: string | null;
  question_count: number;
  total_marks: number;
  submission_count: number;
}

export interface AssignmentDetail {
  id: number;
  group_id: number;
  classified_id: number | null;
  title: string;
  instructions: string | null;
  due_at: string | null;
  question_range: string | null;
  status: string;
  extraction_error: string | null;
  questions: Question[];
}

export interface StudentAssignment {
  id: number;
  title: string;
  instructions: string | null;
  due_at: string | null;
  subject_name: string;
  group_name: string;
  question_count: number;
  total_marks: number;
  submission_status: string | null;
  /** Whether the assignment still accepts a submission. The list includes closed
      assignments (their marks stay in history), so a "Start" action must gate on
      this, not on submission status alone. */
  is_open: boolean;
  my_total: number | null;
  /** When the marks were settled. null until then — the home uses it to tell
      recent results from everything ever marked, and cannot guess a date. */
  finalized_at: string | null;
  /** Whether this student's mark was the best in their class on this piece. A
      boolean about the reader and nothing else — no classmate's mark, count or
      identity is sent — and shown only to the student it is about. False
      whenever there is nothing to compare against, so an absent comparison
      never reads as a bad result. */
  highest_in_class: boolean;
}

export interface MarkRow {
  question_id: number;
  number: string;
  text_summary: string;
  max_marks: number;
  has_mark_scheme: boolean;
  ai_transcription: string | null;
  ai_marks: number | null;
  ai_feedback: string | null;
  ai_confidence: string | null;
  final_marks: number | null;
  final_feedback: string | null;
  overridden: boolean;
  /** Why this row is (or isn't) waiting on the tutor. */
  needs_review: boolean;
  auto_finalized: boolean;
  remark_requested: boolean;
  remark_reason: string | null;
}

export interface ReviewQueueItem {
  submission_id: number;
  assignment_id: number | null;
  past_paper_id: number | null;
  assignment_title: string;
  student_id: number;
  student_name: string;
  submitted_at: string;
  unsure_count: number;
  remark_request_count: number;
}

export interface MarkHistoryEntry {
  old_marks: number | null;
  new_marks: number | null;
  changed_by_name: string;
  reason: string | null;
  created_at: string;
}

export interface RemarkRequestOut {
  id: number;
  question_id: number;
  status: string;
  reason: string | null;
  created_at: string;
}

export interface SubmissionSummary {
  id: number;
  student_id: number;
  student_name: string;
  status: string;
  submitted_at: string;
  total_final: number | null;
  total_max: number;
}

export interface SubmissionFileInfo {
  id: number;
  name: string;
  mime: string;
  position: number;
}

export interface SubmissionDetail {
  id: number;
  /** Exactly one is set: the work is homework or a past paper. */
  assignment_id: number | null;
  past_paper_id: number | null;
  assignment_title: string;
  student_id: number;
  student_name: string;
  status: string;
  ai_error: string | null;
  submitted_at: string;
  files: SubmissionFileInfo[];
  marks: MarkRow[];
}

export interface StudentMarkRow {
  question_id: number | null;
  number: string;
  text_summary: string;
  max_marks: number;
  final_marks: number | null;
  final_feedback: string | null;
  /** Set once the student has asked for this mark to be looked at again. */
  remark_status: string | null;
}

export interface StudentSubmissionView {
  submission_id: number | null;
  status: string;
  submitted_at: string | null;
  finalized_at: string | null;
  total: number | null;
  total_max: number;
  marks: StudentMarkRow[];
}

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

export interface AssignmentAttention {
  assignment_id: number;
  assignment_title: string;
  reason: string;
  detail: string | null;
  submission_id: number | null;
  student_name: string | null;
}

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

/** Fetch a protected file with auth and return an object URL for display.
 *
 * Since task 1.2 (AV-82), the endpoint behind `path` takes one of two shapes
 * (threat review F3): student submissions respond 200 with the bytes directly
 * — the API's ownership check runs on this request, every time. Tutor
 * material (classifieds, past papers, group resources) responds 307 to a
 * short-lived signed object-store URL instead.
 *
 * `fetch()` follows that redirect on its own (`redirect: "follow"` below is
 * the default made explicit, since this function's correctness now depends on
 * it). Browsers strip the `Authorization` header before following a
 * cross-origin redirect — deliberately relied on here: the bearer token must
 * never reach the object store, only Avora's own API.
 *
 * For the redirect path to work in production, the bucket's CORS policy must
 * allow the frontend origin for GET — otherwise `resp.blob()` below rejects.
 * Local disk and MinIO never redirect (`LocalBackend.get_signed_url` returns
 * None), so this only bites once a signing backend is actually configured. */
export async function fetchFileUrl(path: string): Promise<string> {
  const tokens = getStoredTokens();
  const resp = await fetch(apiUrl(path), {
    redirect: "follow",
    headers: tokens ? { Authorization: `Bearer ${tokens.access_token}` } : {},
  });
  if (!resp.ok) throw new Error(`Could not load file (${resp.status})`);
  return URL.createObjectURL(await resp.blob());
}

export const submissionFilePath = (submissionId: number, fileId: number) =>
  `/api/v1/submissions/${submissionId}/files/${fileId}`;
export const classifiedFilePath = (classifiedId: number) =>
  `/api/v1/classifieds/${classifiedId}/file`;
