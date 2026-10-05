import type { UpcomingLesson } from "./groups";
import type { components } from "./schema";
import { api } from "./client";

/**
 * One class on the tutor's home strip.
 *
 * Every absent measurement is null, never 0 — a class with no confident evidence
 * renders as "not enough data yet", not an empty bar (PROD-2, UX-19). Coverage
 * arrives as a pair so the surface can say `9/11`: a status without coverage is
 * a claim about a class made from part of it. `status` is the band from the
 * predicted grade's boundary position, never a percentage threshold (UX-28).
 */
export type ClassStripRow = components["schemas"]["ClassStripRow"];

/** A chapter the class's accepted plan has reached, or reaches within a week,
    with no classified uploaded yet (AV-20, AV-22). */
export type ChapterPrompt = components["schemas"]["ChapterPrompt"];

/** A class whose accepted plan has lessons dated before today with none recorded
    (task 6.6). "Not recorded", not "missed": it may have been taught. */
export type BehindClass = components["schemas"]["BehindClass"];

/**
 * Everything the tutor's home needs, in one response. Replaces a per-class
 * fan-out that itself looped per learner server-side (PERF-1).
 */
export interface TodayView {
  /** Exceptions first: at risk, then needs attention, then healthy. */
  classes: ClassStripRow[];
  /** Today's lessons in the organization's timezone, not the server's. */
  lessons: UpcomingLesson[];
  review_count: number;
  class_count: number;
  joined_student_count: number;
  classes_with_evidence: number;
  /** Optional on the wire (the server defaults it to empty); absent and empty
      both mean render nothing. */
  chapter_prompts?: ChapterPrompt[];
  /** Most unrecorded lessons first; optional on the wire like `chapter_prompts`. */
  behind_classes?: BehindClass[];
}

export const todayView = () => api<TodayView>("/api/v1/today");

/** The Overview's week strip, today's agenda, class cards and remark requests
    (coherence B). Every absent measurement is null, never 0 (PROD-2). */
export type TodayOverview = components["schemas"]["TodayOverview"];
export type WeekGlance = components["schemas"]["WeekGlance"];
export type AgendaItem = components["schemas"]["AgendaItem"];
export type ClassCard = components["schemas"]["ClassCard"];
export type ClassAttention = components["schemas"]["ClassAttention"];
export type RemarkItem = components["schemas"]["RemarkItem"];

export const todayOverview = () => api<TodayOverview>("/api/v1/today/overview");

/** One learner on the class page. `direction` is what NEEDS YOU selects on —
    null means too little history to say, and renders as no arrow at all. */
export type ClassLearnerRow = components["schemas"]["ClassLearnerRow"];
export type ClassWeakTopic = components["schemas"]["ClassWeakTopic"];
export type ClassOverview = components["schemas"]["ClassOverview"];

export const classOverview = (groupId: number) =>
  api<ClassOverview>(`/api/v1/today/classes/${groupId}`);

/** A planned lesson starting within 15 minutes, or under way (task 7.4, AV-120).
    Computed server-side from the accepted plan; in-app only. */
export type LessonReminder = components["schemas"]["LessonReminderOut"];

export const lessonReminders = () => api<LessonReminder[]>("/api/v1/today/reminders");
