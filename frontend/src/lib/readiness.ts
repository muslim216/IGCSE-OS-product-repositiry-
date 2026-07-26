import type { Group } from "../api/groups";
import type { TutorAnalytics } from "../api/readiness";
import type { ReadinessStatus } from "../components/ui";

/* Pure derivation over readiness evidence — no React, unit-testable.
   Shared by the Today dashboard and reusable by readiness / org-level views. */

/** Thresholds match ClassReadinessPage's score coloring. */
export function statusOf(score: number): ReadinessStatus {
  if (score >= 70) return "on_track";
  if (score >= 50) return "needs_attention";
  return "at_risk";
}

export interface LearnerRow {
  student_id: number;
  student_name: string;
  subject_name: string;
  score: number;
  status: ReadinessStatus;
  group_id: number;
  group_name: string;
}

/**
 * Flatten per-group analytics into one learner list. The backend returns every
 * student with confident evidence (lowest scores first, capped per group);
 * students without marked evidence are absent by design — never invented here.
 * A student appearing in several groups for the same subject keeps their
 * lowest score, the one a tutor most needs to see.
 */
export function deriveLearnerRows(
  groups: Group[],
  analytics: (TutorAnalytics | undefined)[],
): LearnerRow[] {
  const byKey = new Map<string, LearnerRow>();
  groups.forEach((group, i) => {
    const data = analytics[i];
    if (!data?.weak_students) return;
    for (const s of data.weak_students) {
      const key = `${s.student_id}:${s.subject_name}`;
      const existing = byKey.get(key);
      if (existing && existing.score <= s.score) continue;
      byKey.set(key, {
        student_id: s.student_id,
        student_name: s.student_name,
        subject_name: s.subject_name,
        score: s.score,
        status: statusOf(s.score),
        group_id: group.id,
        group_name: group.name,
      });
    }
  });
  return [...byKey.values()].sort((a, b) => a.score - b.score);
}

export function greetingFor(hour: number): string {
  if (hour < 12) return "Good morning";
  if (hour < 18) return "Good afternoon";
  return "Good evening";
}
