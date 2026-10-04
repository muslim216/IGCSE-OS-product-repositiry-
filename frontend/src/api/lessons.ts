import { api } from "./client";
import type { components } from "./schema";

/** A taught lesson (`Lesson` server-side): the date and the syllabus topics
 *  covered. Distinct from the weekly timetable slots in `groups.ts`. */
export type TaughtLesson = components["schemas"]["LessonOut"];
export type TaughtLessonBody = components["schemas"]["LessonCreate"];

export const recordLesson = (body: TaughtLessonBody) =>
  api<TaughtLesson>("/api/v1/lessons", { method: "POST", body: JSON.stringify(body) });

export type TaughtLessonPatch = components["schemas"]["LessonUpdate"];

/** Changes a recorded lesson. The server validates the meeting link and clears the
 *  meeting data when the lesson becomes in person. */
export const updateLesson = (lessonId: number, body: TaughtLessonPatch) =>
  api<TaughtLesson>(`/api/v1/lessons/${lessonId}`, { method: "PATCH", body: JSON.stringify(body) });

export type AttendanceRow = components["schemas"]["AttendanceRowOut"];
export type AttendanceState = NonNullable<AttendanceRow["state"]>;

export const listTaughtLessons = (groupId: number) =>
  api<TaughtLesson[]>(`/api/v1/lessons/group/${groupId}`);

/** The register for one lesson. `state: null` means attendance was not taken. */
export const getAttendance = (lessonId: number) =>
  api<AttendanceRow[]>(`/api/v1/lessons/${lessonId}/attendance`);

/** `state: null` clears a mark. */
export const setAttendance = (
  lessonId: number,
  entries: { student_id: number; state: AttendanceState | null }[],
) =>
  api<AttendanceRow[]>(`/api/v1/lessons/${lessonId}/attendance`, {
    method: "PUT",
    body: JSON.stringify({ entries }),
  });
