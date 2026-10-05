import type { components } from "./schema";
import { api } from "./client";

/**
 * The stored weekly send (tasks 8.2, 8.4): what one reader was told about one
 * week, as it stood when the week closed. Exactly one of `tutor`, `student`,
 * `parent` is set — the one `audience` names. A measurement that was absent is
 * null, never 0 (PROD-2).
 */
export type WeeklySend = components["schemas"]["WeeklySendOut"];
export type WeeklySendListItem = components["schemas"]["WeeklySendListItem"];
export type TutorClassFacts = components["schemas"]["TutorClassFacts"];
export type StudentClassFacts = components["schemas"]["StudentClassFacts"];
export type ParentClassFacts = components["schemas"]["ParentClassFacts"];
export type PlanFacts = components["schemas"]["PlanFacts"];
export type AttendanceFacts = components["schemas"]["AttendanceFacts"];
export type HomeworkFacts = components["schemas"]["HomeworkFacts"];

/** The reader's most recent send, or null when none has gone out yet. */
export const latestWeeklySend = () => api<WeeklySend | null>("/api/v1/weekly-sends/latest");

export const weeklySend = (id: number) => api<WeeklySend>(`/api/v1/weekly-sends/${id}`);

/** The reader's own sends, newest first. */
export const myWeeklySends = () => api<WeeklySendListItem[]>("/api/v1/weekly-sends");
