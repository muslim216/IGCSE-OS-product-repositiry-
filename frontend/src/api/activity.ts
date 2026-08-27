import type { components } from "./schema";
import { api } from "./client";

export type ActivityItem = components["schemas"]["ActivityItem"];
export type ActivitySummary = components["schemas"]["ActivitySummary"];

export const myActivity = () => api<ActivitySummary>("/api/v1/me/activity");
