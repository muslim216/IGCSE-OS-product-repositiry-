import { api } from "./client";
import type { components } from "./schema";

// FE-4: aliases of the generated schema, never hand-written interfaces — the
// draft's shape is the backend's `SyllabusDraft` and drifts silently otherwise.
// Input/Output split exists only because the draft has defaulted fields; the
// editor round-trips what the server sent, so it works in Input's terms.
export type SyllabusTopicDraft = components["schemas"]["SyllabusTopicIn-Input"];
export type SyllabusChapterDraft = components["schemas"]["SyllabusChapterIn-Input"];
export type SyllabusDraft = components["schemas"]["SyllabusDraft-Input"];
export type SubjectLevel = components["schemas"]["SubjectLevel"];
export type SyllabusUpload = components["schemas"]["SyllabusUploadOut"];
export type SyllabusUploadDetail = components["schemas"]["SyllabusUploadDetail"];

export const listSyllabusUploads = () => api<SyllabusUpload[]>("/api/v1/syllabus-uploads");
export const getSyllabusUpload = (id: number) =>
  api<SyllabusUploadDetail>(`/api/v1/syllabus-uploads/${id}`);

export function uploadSyllabus(title: string, file: File) {
  const form = new FormData();
  form.append("title", title);
  form.append("file", file);
  return api<SyllabusUploadDetail>("/api/v1/syllabus-uploads", { method: "POST", body: form });
}

export const updateSyllabusDraft = (id: number, draft: SyllabusDraft) =>
  api<SyllabusUploadDetail>(`/api/v1/syllabus-uploads/${id}/draft`, {
    method: "PUT",
    body: JSON.stringify(draft),
  });

export const retrySyllabusExtraction = (id: number) =>
  api<SyllabusUploadDetail>(`/api/v1/syllabus-uploads/${id}/retry`, { method: "POST" });

export const applySyllabusUpload = (id: number) =>
  api<SyllabusUploadDetail>(`/api/v1/syllabus-uploads/${id}/apply`, { method: "POST" });
