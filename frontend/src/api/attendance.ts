import { api } from "./client";
import type { components } from "./schema";

// FE-4: aliases of the generated schema, never hand-written interfaces.
// Attendance is not readiness (AV-33): it is read on its own and shown beside it.
export type StudentAttendance = components["schemas"]["StudentAttendanceOut"];
export type ClassAttendance = components["schemas"]["ClassAttendanceOut"];
export type RecentLesson = components["schemas"]["RecentLessonOut"];

/** The signed-in student's own attendance. The server reads the id from the token. */
export const myAttendance = () => api<StudentAttendance>("/api/v1/me/attendance");

/** A child's (parent) or a student's (tutor) attendance; refused with 404 otherwise. */
export const studentAttendance = (studentId: number) =>
  api<StudentAttendance>(`/api/v1/students/${studentId}/attendance`);
