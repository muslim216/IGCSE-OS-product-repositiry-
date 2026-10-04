import type { components } from "../api/schema";

/* The one verdict per (student, subject), worded per role.

   The decision is made once on the server (services/student_verdict.py) and
   arrives identically for the tutor, the student and the parent. This file is
   the only place the roles diverge, and they diverge in wording only: the
   student's is kinder. Nothing here recomputes a status. */

export type StudentVerdict = components["schemas"]["SubjectVerdict"];
export type VerdictRole = "tutor" | "student" | "parent";

export interface VerdictWording {
  /** The whole line — "Needs attention: Ionic bonding, Moles". */
  line: string;
  /** The status on its own, for a badge. */
  label: string;
  /** The weakest topics joined, or null when there are none to name. */
  reason: string | null;
  nextStep: string;
}

const NOT_ENOUGH = "Not enough data yet";

const ADULT_LABEL: Record<"on_track" | "needs_attention" | "at_risk", string> = {
  on_track: "On track",
  needs_attention: "Needs attention",
  at_risk: "At risk",
};

export function wordingFor(role: VerdictRole, verdict: StudentVerdict): VerdictWording {
  const topics = verdict.reason_topics ?? [];
  const reason = topics.length > 0 ? topics.join(", ") : null;
  const nextStep = verdict.next_step;

  const status = verdict.status;
  switch (status) {
    case "not_enough_data":
      return { line: NOT_ENOUGH, label: NOT_ENOUGH, reason: null, nextStep };
    case "on_track": {
      const label = role === "student" ? "You're on track" : ADULT_LABEL.on_track;
      return { line: label, label, reason: null, nextStep };
    }
    case "needs_attention":
    case "at_risk": {
      if (role === "student") {
        const label = reason ? "Focus on" : "Worth a closer look";
        return { line: reason ? `Focus on: ${reason}` : label, label, reason, nextStep };
      }
      const label = ADULT_LABEL[status];
      return { line: reason ? `${label}: ${reason}` : label, label, reason, nextStep };
    }
    default: {
      // A new server status must be worded here before this compiles.
      const unreachable: never = status;
      return unreachable;
    }
  }
}

const SEVERITY: Record<string, number> = { at_risk: 0, needs_attention: 1, on_track: 2 };

/** Subjects that have a verdict to give, most urgent first (stable within a
    severity). not_enough_data is excluded: it is absence, not a rank. */
export function measuredBySeverity<T extends { verdict: StudentVerdict }>(subjects: T[]): T[] {
  return subjects
    .filter((s) => s.verdict.status in SEVERITY)
    .map((s, i) => ({ s, i }))
    .sort((a, b) => SEVERITY[a.s.verdict.status] - SEVERITY[b.s.verdict.status] || a.i - b.i)
    .map(({ s }) => s);
}
