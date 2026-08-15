/* One home for user-facing strings that more than one surface says.

   Copy lives with the component that renders it, with one exception: a string
   that answers the *same condition* in two places. Two copies drift — this file
   exists because they already had. REASON_LABELS was duplicated, and the copy
   the tutor's home imported was missing a key, so the most common reason
   rendered on that surface as the raw enum `needs_review`. */

/** Why a piece of work is waiting on the tutor.
 *
 * Exactly these four, matching what the backend sends: `extraction_failed`
 * from api/assignments.py, and the three Submission statuses that endpoint
 * filters to — `ai_failed`, `ai_marked`, `needs_review`. A reason added to the
 * backend is added here in the same change (FE-4).
 */
export const REASON_LABELS: Record<string, string> = {
  extraction_failed: "Question extraction failed",
  ai_failed: "AI marking failed",
  ai_marked: "AI-marked — awaiting your review",
  needs_review: "Some marks need your decision",
};

/** Where a piece of evidence came from, in words.
 *
 * Mirrors `EvidenceSource` in backend/app/models/readiness.py. A member added
 * there is added here in the same change (FE-4) — the fallback below keeps a
 * missing key from crashing a page, but it renders the raw enum, which is not
 * something a tutor should ever be shown.
 *
 * `tutor_estimate` is **self-declared**: it is a tutor's own judgement rather
 * than a mark on a piece of work, and PROD-8 requires that to be visible
 * wherever it is shown, not only where it was entered. That is why the label
 * carries the words rather than leaving them to each caller.
 */
export const SOURCE_LABELS: Record<string, string> = {
  past_paper: "Past paper",
  mock: "Mock",
  homework: "Homework",
  quiz: "Quiz",
  observation: "Tutor observation",
  tutor_estimate: "Tutor's estimate (self-declared)",
};

export function sourceLabel(source: string): string {
  return SOURCE_LABELS[source] ?? source;
}

/** Absent states, in words.
 *
 * A missing measurement is never a `0`, an empty bar or a dash — it is a
 * sentence saying it is missing (PROD-2, UX-19). These are the shared wordings
 * so the same condition never gets two of them.
 */
export const ABSENT = {
  noEvidence: "not enough data yet",
  noBoundaries: "no grade boundaries set",
  noBoundariesAction: "Set them →",
  updating: "Updating…",
  aiUnavailable: "Guidance is unavailable right now.",
  loadFailed: "This is usually temporary — refresh the page to try again.",
} as const;
