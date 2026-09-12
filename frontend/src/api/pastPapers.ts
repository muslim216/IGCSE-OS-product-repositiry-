import { api } from "./client";
import type { components } from "./schema";

/** Aliased from the generated schema rather than hand-mirrored (`FE-4`).
 *
 *  The AI names the paper at extraction time, so `title` is **null** until that
 *  has run — as are `session_label` and `paper_number`. Render `display_title`,
 *  which is the same value with the server's "Untitled paper" fallback already
 *  applied; read `title` only where you need to know whether a real name exists
 *  yet, such as a form that writes one back. */
export type PastPaper = components["schemas"]["PastPaperOut"];
export type PastPaperDetail = components["schemas"]["PastPaperDetail"];
export type PastPaperAttempt = components["schemas"]["PastPaperAttemptOut"];

export const listPastPapers = (subjectId?: number) =>
  api<PastPaper[]>(`/api/v1/past-papers${subjectId ? `?subject_id=${subjectId}` : ""}`);

export const getPastPaper = (id: number) => api<PastPaperDetail>(`/api/v1/past-papers/${id}`);

export function uploadPastPaper(payload: {
  subject_id: number;
  booklet: File;
  /** Required: a full paper's marks can't rest on the AI's judgement alone. */
  mark_scheme: File;
  total_marks?: number | null;
  duration_minutes?: number | null;
}) {
  const form = new FormData();
  form.append("subject_id", String(payload.subject_id));
  form.append("booklet", payload.booklet);
  form.append("mark_scheme", payload.mark_scheme);
  if (payload.total_marks) form.append("total_marks", String(payload.total_marks));
  if (payload.duration_minutes) form.append("duration_minutes", String(payload.duration_minutes));
  return api<PastPaper>("/api/v1/past-papers", { method: "POST", body: form });
}

export function logAttempt(
  pastPaperId: number,
  payload: {
    files: File[];
    attempted_at: string;
    timed: boolean;
    time_taken_minutes: number | null;
  },
) {
  const form = new FormData();
  for (const f of payload.files) form.append("files", f);
  form.append("attempted_at", payload.attempted_at);
  form.append("timed", String(payload.timed));
  if (payload.time_taken_minutes)
    form.append("time_taken_minutes", String(payload.time_taken_minutes));
  return api<PastPaperAttempt>(`/api/v1/past-papers/${pastPaperId}/attempts`, {
    method: "POST",
    body: form,
  });
}

export const myAttempt = (pastPaperId: number) =>
  api<PastPaperAttempt | null>(`/api/v1/past-papers/${pastPaperId}/my-attempt`);

export const pastPaperBookletPath = (id: number) => `/api/v1/past-papers/${id}/booklet`;
export const pastPaperMarkSchemePath = (id: number) => `/api/v1/past-papers/${id}/mark-scheme`;
