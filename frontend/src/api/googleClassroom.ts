import { api } from "./client";

export interface GoogleAccountInfo {
  connected: boolean;
  /** False when the server has no Google credentials set at all. */
  configured: boolean;
  google_email: string | null;
  status: string | null;
  missing_scopes: string[];
  last_error: string | null;
  connected_at: string | null;
}

export interface GoogleCourse {
  course_id: string;
  name: string;
  section: string | null;
  linked_group_id: number | null;
}

export interface GoogleCoursework {
  coursework_id: string;
  title: string;
  linked_assignment_id: number | null;
}

export interface CourseLink {
  id: number;
  course_id: string;
  course_name: string | null;
  group_id: number;
}

export interface RosterEntry {
  google_user_id: string;
  google_name: string | null;
  google_email: string | null;
  mapped_student_id: number | null;
  suggested_student_id: number | null;
}

export interface Roster {
  classroom_students: RosterEntry[];
  app_students_not_in_classroom: { student_id: number; name: string }[];
}

export interface ImportResultRow {
  google_user_id: string;
  outcome: string;
  detail: string | null;
  imported_file_count: number;
}

export interface ImportRun {
  id: number;
  status: "pending" | "running" | "done" | "failed";
  total: number;
  imported: number;
  skipped: number;
  failed: number;
  error: string | null;
  finished_at: string | null;
  results: ImportResultRow[];
}

export const googleAccount = () => api<GoogleAccountInfo>("/api/v1/google/account");
export const startGoogleOAuth = () =>
  api<{ authorize_url: string }>("/api/v1/google/oauth/start", { method: "POST" });
export const disconnectGoogle = () =>
  api<void>("/api/v1/google/account", { method: "DELETE" });

export const listGoogleCourses = () => api<GoogleCourse[]>("/api/v1/google/courses");
export const listGoogleCoursework = (courseId: string) =>
  api<GoogleCoursework[]>(`/api/v1/google/courses/${courseId}/coursework`);

export const linkCourse = (course_id: string, group_id: number) =>
  api<CourseLink>("/api/v1/google/course-links", {
    method: "POST",
    body: JSON.stringify({ course_id, group_id }),
  });

export const courseRoster = (linkId: number) =>
  api<Roster>(`/api/v1/google/course-links/${linkId}/roster`);
export const saveRoster = (
  linkId: number,
  mappings: { google_user_id: string; student_id: number | null }[],
) =>
  api<Roster>(`/api/v1/google/course-links/${linkId}/roster`, {
    method: "PUT",
    body: JSON.stringify(mappings),
  });

export const startImport = (linkId: number, courseworkId: string, assignment_id: number) =>
  api<ImportRun>(
    `/api/v1/google/course-links/${linkId}/coursework/${courseworkId}/import`,
    { method: "POST", body: JSON.stringify({ assignment_id }) },
  );
export const getImportRun = (runId: number) =>
  api<ImportRun>(`/api/v1/google/import-runs/${runId}`);
