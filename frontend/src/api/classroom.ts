import { api } from "./client";

export interface ClassroomStatus {
  /** False when the deployment has no Google OAuth credentials at all. */
  configured: boolean;
  connected: boolean;
  google_email: string | null;
  connected_at: string | null;
}

export interface ClassroomAuthUrl {
  url: string;
  state: string;
}

export interface ClassroomCourse {
  id: string;
  name: string;
}

export interface ClassroomLink {
  id: number;
  group_id: number;
  group_name: string;
  classroom_course_id: string;
  classroom_course_name: string;
  last_synced_at: string | null;
}

export const classroomStatus = () => api<ClassroomStatus>("/api/v1/classroom/status");

export const classroomAuthUrl = () =>
  api<ClassroomAuthUrl>("/api/v1/classroom/auth-url");

export const connectClassroom = (code: string) =>
  api<ClassroomStatus>("/api/v1/classroom/connect", {
    method: "POST",
    body: JSON.stringify({ code }),
  });

export const disconnectClassroom = () =>
  api<void>("/api/v1/classroom/account", { method: "DELETE" });

export const listClassroomCourses = () =>
  api<ClassroomCourse[]>("/api/v1/classroom/courses");

export const listClassroomLinks = () =>
  api<ClassroomLink[]>("/api/v1/classroom/links");

export const createClassroomLink = (payload: {
  group_id: number;
  classroom_course_id: string;
  classroom_course_name: string;
}) =>
  api<ClassroomLink>("/api/v1/classroom/links", {
    method: "POST",
    body: JSON.stringify(payload),
  });

export const deleteClassroomLink = (linkId: number) =>
  api<void>(`/api/v1/classroom/links/${linkId}`, { method: "DELETE" });

export const syncClassroom = () =>
  api<{ queued: boolean }>("/api/v1/classroom/sync", { method: "POST" });
