import { api, apiUrl, getStoredTokens } from "./client";
import type { components } from "./schema";
import type { AttemptRedo } from "./students";
import type { Topic } from "./syllabus";

/** A classified: past-paper questions compiled by topic, uploaded once and reused. Chapter-scoped
 *  since task 3.1 (`AV-20`), and carrying that chapter's marking notes
 *  (`AV-21`) — the layer of `AV-76`'s precedence directly below the official
 *  mark scheme. Aliased from the generated schema rather than hand-mirrored
 *  (`FE-4`). */
export type Classified = components["schemas"]["ClassifiedOut"];

/** Mirrors `MAX_CLASSIFIED_NOTES` in backend/app/schemas/homework.py, which is
 *  the control — this one is so the tutor sees the limit while typing rather
 *  than as a rejected save. */
export const MAX_CLASSIFIED_NOTES = 4000;

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

/** A student's typed answer as the tutor sees it (`AV-73`). Carries the
    deterministic scan's verdict, which the student's own view does not. */
export type TypedAnswer = components["schemas"]["TypedAnswerOut"];

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

/** One mistake tagged against a question (4.2), as the
    tutor sees it. Tutor-only, like `scheme_conflict`: `StudentMarkRow` has no
    such field, and what a student sees about their own mistake pattern is
    `AV-41`'s homework tab, not this screen. */
export type MistakeRow = components["schemas"]["MistakeRow"];

export type MarkRow = components["schemas"]["MarkRow"];

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

/** The tutor's view of one submission, aliased from the generated schema rather
 *  than hand-mirrored (`FE-4`). `can_redo` is whether "Let them redo this" is on
 *  offer: decided by the server with the same rule the redo endpoint raises from. */
export type SubmissionDetail = components["schemas"]["SubmissionDetail"];

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

/** Re-file a classified under a chapter and rewrite its marking notes. A full
 *  replacement of that pair, not a partial patch — the editor holds both. */
export const updateClassified = (
  classifiedId: number,
  payload: { chapter_id: number | null; notes: string },
) =>
  api<Classified>(`/api/v1/classifieds/${classifiedId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });

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
  chapter_id?: number | null;
  notes?: string;
}) {
  const form = new FormData();
  form.append("group_id", String(payload.group_id));
  form.append("file", payload.file);
  if (payload.mark_scheme) form.append("mark_scheme", payload.mark_scheme);
  if (payload.title) form.append("title", payload.title);
  if (payload.instructions) form.append("instructions", payload.instructions);
  if (payload.due_at) form.append("due_at", payload.due_at);
  if (payload.question_range) form.append("question_range", payload.question_range);
  if (payload.chapter_id) form.append("chapter_id", String(payload.chapter_id));
  if (payload.notes) form.append("notes", payload.notes);
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

/** Aliased from the generated schema (`FE-4`). Homework, or a past paper the
 *  AI could not read: exactly one of `assignment_id` and `past_paper_id` is
 *  set. Link to an item with `attentionHref` in `lib/attention.ts`. */
export type AssignmentAttention = components["schemas"]["AssignmentAttention"];

export const assignmentsNeedingAttention = () =>
  api<AssignmentAttention[]>("/api/v1/assignments/attention");

export const myAssignments = () => api<StudentAssignment[]>("/api/v1/me/assignments");
export const mySubmission = (assignmentId: number) =>
  api<StudentSubmissionView>(`/api/v1/assignments/${assignmentId}/my-submission`);

/** Mirrors `MAX_TYPED_ANSWER` in backend/app/schemas/homework.py, which is the
    control — this one is so the student sees the limit while typing rather than
    as a rejected submission. */
export const MAX_TYPED_ANSWER = 20000;

/** Photos, typed text, or both (`AV-73`). Neither is not a submission, and the
    server says so. */
export function submitWork(assignmentId: number, files: File[], typedAnswer = "") {
  const form = new FormData();
  for (const f of files) form.append("files", f);
  if (typedAnswer.trim()) form.append("typed_answer", typedAnswer);
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
/** Change the category or severity of a tagged mistake (`AV-38`). Works on a
    finalized submission: a tag is the tutor's own note, not part of the
    student's result. Returns the whole submission, as saving marks does. */
export const reviseMistake = (
  submissionId: number,
  mistakeId: number,
  revision: { category_id: number; severity: number },
) =>
  api<SubmissionDetail>(`/api/v1/submissions/${submissionId}/mistakes/${mistakeId}`, {
    method: "PATCH",
    body: JSON.stringify(revision),
  });

export const finalizeSubmission = (id: number) =>
  api<SubmissionDetail>(`/api/v1/submissions/${id}/finalize`, { method: "POST" });

/** Set a locked attempt aside so the student can hand the work in again. The
    old attempt stops counting toward readiness; a record of it is kept. */
export const redoAttempt = (id: number) =>
  api<AttemptRedo>(`/api/v1/submissions/${id}/redo`, { method: "POST" });

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
export const classifiedMarkSchemePath = (classifiedId: number) =>
  `/api/v1/classifieds/${classifiedId}/mark-scheme`;

/** One piece of homework in the tutor's cross-class list, with plain counts of
 *  students and hand-ins, nothing derived (`FE-4`). */
export type TutorHomework = components["schemas"]["TutorHomeworkRow"];

/** The list with the server's own word on whether it was cut short, and the cap
 *  it applied, so no number is mirrored here. */
export type TutorHomeworkList = components["schemas"]["TutorHomeworkList"];

export const listMyHomework = () => api<TutorHomeworkList>("/api/v1/assignments");
