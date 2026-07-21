import { api } from "./client";

export interface GradeBoundary {
  grade: string;
  min: number;
}

export interface SyllabusTopicDraft {
  code: string;
  title: string;
  weight: number;
  children: SyllabusTopicDraft[];
}

export interface SyllabusDraft {
  exam_board: string;
  code: string;
  name: string;
  grade_scale: string;
  grade_boundaries: GradeBoundary[];
  topics: SyllabusTopicDraft[];
}

export interface SyllabusUpload {
  id: number;
  title: string;
  file_name: string;
  status: "extracting" | "extraction_failed" | "review" | "applied";
  error: string | null;
  subject_id: number | null;
  created_at: string;
}

export interface SyllabusUploadDetail extends SyllabusUpload {
  draft: SyllabusDraft | null;
}

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
