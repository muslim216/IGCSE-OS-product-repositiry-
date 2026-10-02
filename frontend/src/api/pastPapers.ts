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
  paper: File;
  /** Optional. Without it the paper is still marked, but nothing
   *  auto-finalizes — every mark waits in the tutor's review queue. */
  mark_scheme?: File | null;
  total_marks?: number | null;
  duration_minutes?: number | null;
}) {
  const form = new FormData();
  form.append("subject_id", String(payload.subject_id));
  form.append("paper", payload.paper);
  if (payload.mark_scheme) form.append("mark_scheme", payload.mark_scheme);
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

/** Reads a paper the AI couldn't read once more — for a failure in the
 *  reading, such as the model being unavailable. Refused (409) for any paper
 *  that isn't waiting on a fix. */
export const retryPastPaper = (id: number) =>
  api<PastPaper>(`/api/v1/past-papers/${id}/retry-extraction`, { method: "POST" });

/** Swaps a clearer copy in for a paper the AI couldn't read, then reads it.
 *  The same paper carries on, so students' answers already sent for it are
 *  marked against the new copy's questions. */
export function replacePastPaper(id: number, paper: File) {
  const form = new FormData();
  form.append("paper", paper);
  return api<PastPaper>(`/api/v1/past-papers/${id}/paper`, { method: "PUT", body: form });
}

/** Takes the paper off the tutor's own list. **Students keep it** — the row
 *  carries their attempts and the evidence those produced (`PROD-5`), so the
 *  server sets a hidden flag rather than deleting anything. */
export const hidePastPaper = (id: number) =>
  api<void>(`/api/v1/past-papers/${id}`, { method: "DELETE" });

export const pastPaperPaperPath = (id: number) => `/api/v1/past-papers/${id}/paper`;
export const pastPaperMarkSchemePath = (id: number) => `/api/v1/past-papers/${id}/mark-scheme`;
