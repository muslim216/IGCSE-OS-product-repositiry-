import type { components } from "./schema";
import { api } from "./client";

/** `audience` and `status` are plain `str` in the OpenAPI schema; the literal
    unions are frontend refinements (surfaces branch on the exact value), kept
    here while the rest of the shape is anchored to the generated type. */
export type Report = Omit<components["schemas"]["ReportOut"], "audience" | "status"> & {
  audience: "student" | "tutor" | "parent";
  status: "generating" | "ready" | "failed";
};

export type ReportDetail = Omit<components["schemas"]["ReportDetail"], "audience" | "status"> & {
  audience: "student" | "tutor" | "parent";
  status: "generating" | "ready" | "failed";
};

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
