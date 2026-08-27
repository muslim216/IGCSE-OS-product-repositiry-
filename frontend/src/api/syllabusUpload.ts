import type { components } from "./schema";
import { api } from "./client";

export type GradeBoundary = components["schemas"]["GradeBoundaryIn"];

/** The draft topic tree. Input and Output variants of the generated schema are
    structurally identical; the Output one is used for the read path and passed
    back unchanged on the write path. */
export type SyllabusTopicDraft = components["schemas"]["SyllabusTopicIn-Output"];

export type SyllabusDraft = components["schemas"]["SyllabusDraft-Output"];

/** `status` is a plain `str` in the OpenAPI schema; the four-value union is a
    frontend refinement (surfaces branch on the exact value), kept here while
    the rest of the shape is anchored to the generated type. */
type SyllabusUploadStatus = "extracting" | "extraction_failed" | "review" | "applied";

export type SyllabusUpload = Omit<components["schemas"]["SyllabusUploadOut"], "status"> & {
  status: SyllabusUploadStatus;
};

export type SyllabusUploadDetail = Omit<components["schemas"]["SyllabusUploadDetail"], "status"> & {
  status: SyllabusUploadStatus;
};

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
