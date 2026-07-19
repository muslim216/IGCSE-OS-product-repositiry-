import { api, getStoredTokens } from "./client";
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
  classified_id: number;
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
  my_total: number | null;
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
  assignment_id: number;
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
  number: string;
  text_summary: string;
  max_marks: number;
  final_marks: number | null;
  final_feedback: string | null;
}

export interface StudentSubmissionView {
  status: string;
  submitted_at: string | null;
  finalized_at: string | null;
  total: number | null;
  total_max: number;
  marks: StudentMarkRow[];
}

export const listClassifieds = (subjectId?: number) =>
  api<Classified[]>(
    `/api/v1/classifieds${subjectId ? `?subject_id=${subjectId}` : ""}`,
  );

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

export const createAssignment = (payload: {
  group_id: number;
  classified_id: number;
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
export const getAssignment = (id: number) =>
  api<AssignmentDetail>(`/api/v1/assignments/${id}`);
export const replaceQuestions = (id: number, questions: QuestionIn[]) =>
  api<AssignmentDetail>(`/api/v1/assignments/${id}/questions`, {
    method: "PUT",
    body: JSON.stringify(questions),
  });
export const publishAssignment = (id: number) =>
  api<AssignmentDetail>(`/api/v1/assignments/${id}/publish`, { method: "POST" });
export const retryExtraction = (id: number) =>
  api<AssignmentDetail>(`/api/v1/assignments/${id}/retry-extraction`, { method: "POST" });

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
export const getSubmission = (id: number) =>
  api<SubmissionDetail>(`/api/v1/submissions/${id}`);
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

/** Fetch a protected file with auth and return an object URL for display. */
export async function fetchFileUrl(path: string): Promise<string> {
  const tokens = getStoredTokens();
  const resp = await fetch(path, {
    headers: tokens ? { Authorization: `Bearer ${tokens.access_token}` } : {},
  });
  if (!resp.ok) throw new Error(`Could not load file (${resp.status})`);
  return URL.createObjectURL(await resp.blob());
}

export const submissionFilePath = (submissionId: number, fileId: number) =>
  `/api/v1/submissions/${submissionId}/files/${fileId}`;
export const classifiedFilePath = (classifiedId: number) =>
  `/api/v1/classifieds/${classifiedId}/file`;
