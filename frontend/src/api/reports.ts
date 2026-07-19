import { api } from "./client";

export interface Report {
  id: number;
  student_id: number;
  subject_id: number | null;
  audience: "student" | "tutor" | "parent";
  status: "generating" | "ready" | "failed";
  title: string;
  created_at: string;
  generated_at: string | null;
}

export interface ReportDetail extends Report {
  content: string | null;
  error: string | null;
}

export const listReports = (studentId: number) =>
  api<Report[]>(`/api/v1/reports?student_id=${studentId}`);
export const getReport = (id: number) => api<ReportDetail>(`/api/v1/reports/${id}`);
export const generateReport = (payload: {
  student_id: number;
  audience: string;
  subject_id?: number | null;
}) =>
  api<ReportDetail>("/api/v1/reports/generate", {
    method: "POST",
    body: JSON.stringify(payload),
  });
