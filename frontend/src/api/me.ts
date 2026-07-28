import { api } from "./client";

export interface ActivityItem {
  kind: string;
  label: string;
  sublabel: string | null;
  link: string;
  occurred_at: string;
}

export interface ActivitySummary {
  count: number;
  items: ActivityItem[];
}

export const myActivity = () => api<ActivitySummary>("/api/v1/me/activity");
