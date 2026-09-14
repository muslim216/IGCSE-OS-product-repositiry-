import { api } from "./client";
import type { components } from "./schema";

/** Aliased from the generated schema rather than hand-mirrored (`FE-4`).
 *
 *  A booklet is one uploaded PDF holding several whole past papers. The AI
 *  reads the list of papers out of it; the tutor corrects that list and
 *  approves it, and only then are real `PastPaper` rows cut from the file. */
export type Booklet = components["schemas"]["BookletOut"];
export type BookletDetail = components["schemas"]["BookletDetail"];
export type BookletDraft = components["schemas"]["BookletDraft"];
export type DraftPaper = components["schemas"]["DraftPaper"];

export const listBooklets = (subjectId?: number) =>
  api<Booklet[]>(`/api/v1/booklets${subjectId ? `?subject_id=${subjectId}` : ""}`);

export const getBooklet = (id: number) => api<BookletDetail>(`/api/v1/booklets/${id}`);

export function uploadBooklet(payload: {
  subject_id: number;
  /** Must be a PDF — a booklet is several papers bound into one file, which a
   *  photo cannot be. The server rejects anything else. */
  file: File;
  /** Optional, and the same trade as a single paper's: without it nothing
   *  auto-finalizes, and the AI has no second reading to check the split
   *  against. */
  mark_scheme?: File | null;
}) {
  const form = new FormData();
  form.append("subject_id", String(payload.subject_id));
  form.append("file", payload.file);
  if (payload.mark_scheme) form.append("mark_scheme", payload.mark_scheme);
  return api<BookletDetail>("/api/v1/booklets", { method: "POST", body: form });
}

/** The whole draft goes back, not a patch — `scheme_papers` and
 *  `scheme_mismatch` ride along so an edit does not silently drop the AI's
 *  reading of the mark scheme. */
export const saveBookletDraft = (id: number, draft: BookletDraft) =>
  api<BookletDetail>(`/api/v1/booklets/${id}/draft`, {
    method: "PUT",
    body: JSON.stringify(draft),
  });

export const retryBookletExtraction = (id: number) =>
  api<BookletDetail>(`/api/v1/booklets/${id}/retry`, { method: "POST" });

export const approveBooklet = (id: number) =>
  api<BookletDetail>(`/api/v1/booklets/${id}/approve`, { method: "POST" });

export const bookletFilePath = (id: number) => `/api/v1/booklets/${id}/file`;
export const bookletMarkSchemePath = (id: number) => `/api/v1/booklets/${id}/mark-scheme`;
