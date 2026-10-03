import { api } from "./client";
import type { components } from "./schema";

/** A taught lesson (`Lesson` server-side): the date and the syllabus topics
 *  covered. Distinct from the weekly timetable slots in `groups.ts`. */
export type TaughtLesson = components["schemas"]["LessonOut"];
export type TaughtLessonBody = components["schemas"]["LessonCreate"];

export const recordLesson = (body: TaughtLessonBody) =>
  api<TaughtLesson>("/api/v1/lessons", { method: "POST", body: JSON.stringify(body) });
