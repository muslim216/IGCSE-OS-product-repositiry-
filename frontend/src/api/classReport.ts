import type { components } from "./schema";
import { api } from "./client";

/**
 * The tutor's class report (task 8.6). Every absent measurement is null, never
 * 0 (PROD-2): the page says "not enough data yet" for it. The parent's report
 * is a different document and is not read from here.
 */
export type ClassReport = components["schemas"]["ClassReport"];
export type PlanReport = components["schemas"]["PlanReport"];
export type ChapterReport = components["schemas"]["ChapterReport"];
export type TopicReport = components["schemas"]["TopicReport"];
export type MistakePatterns = components["schemas"]["MistakePatterns"];
export type AttendanceReport = components["schemas"]["AttendanceReport"];

/** `since` (ISO date) opens the mistake window only; the server defaults it to four weeks back. */
export const classReport = (groupId: number, since?: string) =>
  api<ClassReport>(`/api/v1/groups/${groupId}/report${since ? `?since=${since}` : ""}`);
