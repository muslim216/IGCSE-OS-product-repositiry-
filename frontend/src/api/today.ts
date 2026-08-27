import type { ReadinessStatus } from "../components/ui";
import type { components } from "./schema";
import { api, type Present } from "./client";

/**
 * One class on the tutor's home strip.
 *
 * Every absent measurement is null, never 0 — a class with no confident evidence
 * renders as "not enough data yet", not an empty bar (PROD-2, UX-19). Coverage
 * arrives as a pair (`students_with_evidence` over `member_count`) so the
 * surface can say `9/11`: a status without coverage is a claim about a class
 * made from part of it. `status` is a plain `str` in the OpenAPI schema; the
 * `ReadinessStatus` band is a frontend refinement (it drives the colour a
 * surface shows, UX-28), kept here while the rest is anchored to the generated
 * type. `boundaries_missing` means the subject has no boundaries in either
 * source, so the surface offers "Set them →" rather than silently showing no
 * grade.
 */
export type ClassStripRow = Present<Omit<components["schemas"]["ClassStripRow"], "status">> & {
  status: ReadinessStatus | null;
};

/**
 * Everything the tutor's home needs, in one response. Replaces a per-class
 * fan-out that itself looped per learner server-side (PERF-1). `classes` are
 * exceptions first: at risk, then needs attention, then healthy. `lessons` are
 * today's lessons in the organization's timezone, not the server's.
 */
export type TodayView = Omit<components["schemas"]["TodayView"], "classes"> & {
  classes: ClassStripRow[];
};

export const todayView = () => api<TodayView>("/api/v1/today");

/** One learner on the class page. `direction` is what NEEDS YOU selects on —
    null means too little history to say, and renders as no arrow at all.
    `status`/`direction` are plain `str` in the OpenAPI schema; the literal
    refinements are kept here (see ClassStripRow). */
export type ClassLearnerRow = Present<
  Omit<components["schemas"]["ClassLearnerRow"], "status" | "direction">
> & {
  status: ReadinessStatus | null;
  direction: "up" | "flat" | "down" | null;
};

export type ClassWeakTopic = components["schemas"]["ClassWeakTopic"];

/** `needs_you` is selected on direction, not level: declining learners the
    tutor can help. */
export type ClassOverview = Present<
  Omit<components["schemas"]["ClassOverview"], "status" | "needs_you" | "learners">
> & {
  status: ReadinessStatus | null;
  needs_you: ClassLearnerRow[];
  learners: ClassLearnerRow[];
};

export const classOverview = (groupId: number) =>
  api<ClassOverview>(`/api/v1/today/classes/${groupId}`);
