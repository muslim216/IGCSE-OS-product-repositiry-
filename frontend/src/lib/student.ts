import type { StudentAssignment } from "../api/homework";
import type { SubjectReadiness } from "../api/readiness";
import { countWord } from "./verdict";

/* Pure derivations for the student's surfaces — no React, unit-testable, and in
   one place so the home and Progress cannot answer the same question two ways.

   The rule underneath all of it: a student's home is read every day, and a
   number on it is read as a statement about the person. So every value here is
   either paired with movement or omitted, and nothing is ever averaged across
   subjects. */

/** How recently a piece must have been marked to count as news.
 *
 * Seven days, not "since you last looked": a student who opens the app twice on
 * one day would otherwise see YOU DID empty the second time, which reads as the
 * achievement having been taken away. */
export const RECENTLY_MARKED_DAYS = 7;

/** Movement smaller than this is not reported as movement.
 *
 * Mirrors DIRECTION_NOISE_BAND in services/readiness_summary.py, and for the
 * same reason: a readiness score is a noisy estimate, so without a dead-zone the
 * smallest recomputation becomes "you're up 1 this month". The backend already
 * applies this to the arrow; this applies it to the sentence, so the two agree
 * on what counts as a change. */
export const MOVEMENT_NOISE_BAND = 3;

/**
 * The cross-subject average is deliberately absent from this file.
 *
 * `StudentHomePage` used to mean-average every subject's readiness into one
 * "Overall readiness" figure. Subjects have different scales, different
 * coverage and different boundaries, so that mean was arithmetically
 * meaningless — and it was the first thing a student saw every day. Readiness
 * is a per-subject concept and is presented as one (experience-design §5.1).
 * If a future surface wants one number for a student, it needs a defined
 * derivation, not a mean over incomparable values.
 */

export interface SubjectValue {
  subject_id: number;
  subject_name: string;
  /** null when there is no confident evidence — rendered in words, never as 0. */
  score: number | null;
  direction: SubjectReadiness["direction"];
  status: SubjectReadiness["status"];
}

/** The subject strip, in a stable order so it does not reshuffle between visits
    as scores move — a strip that reorders itself makes the reader hunt for
    their own subjects and turns every visit into a ranking. */
export function subjectStrip(subjects: SubjectReadiness[]): SubjectValue[] {
  return [...subjects]
    .sort((a, b) => a.subject_name.localeCompare(b.subject_name))
    .map((s) => ({
      subject_id: s.subject_id,
      subject_name: s.subject_name,
      score: s.score === null ? null : Math.round(s.score),
      direction: s.direction,
      status: s.status,
    }));
}

/** Line one of the home (copy §4.5). Ends in a full stop — a verdict without
    one reads as a label. */
export function dueVerdict(dueCount: number): string {
  if (dueCount === 0) return "You're clear. Nothing due.";
  const word = countWord(dueCount);
  return `${word.charAt(0).toUpperCase()}${word.slice(1)} thing${dueCount === 1 ? "" : "s"} to do today.`;
}

function markedAgeDays(assignment: StudentAssignment, now: number): number | null {
  if (!assignment.finalized_at) return null;
  const at = Date.parse(assignment.finalized_at);
  return Number.isNaN(at) ? null : (now - at) / 86_400_000;
}

/**
 * Work marked in the last week, newest first — the YOU DID section.
 *
 * Filtered on `finalized_at` rather than on status alone. Without a date the
 * only honest section header would be "things that have been marked at some
 * point", which is every piece the student has ever submitted and is not news.
 * A piece with no `finalized_at` is therefore excluded rather than assumed
 * recent.
 */
export function recentlyMarked(
  assignments: StudentAssignment[],
  now: number = Date.now(),
): StudentAssignment[] {
  return assignments
    .filter((a) => {
      const age = markedAgeDays(a, now);
      return a.my_total !== null && age !== null && age >= 0 && age <= RECENTLY_MARKED_DAYS;
    })
    .sort((a, b) => Date.parse(b.finalized_at!) - Date.parse(a.finalized_at!));
}

/**
 * Subjects that have moved enough this month to be worth saying out loud.
 *
 * Only improvements. A student's home is not where they are told they are going
 * backwards — the decline is already visible on the strip above, paired with
 * its arrow, where it is a fact rather than an announcement.
 */
export function monthlyGains(subjects: SubjectReadiness[]): SubjectReadiness[] {
  return subjects
    .filter((s) => s.month_delta !== null && s.month_delta > MOVEMENT_NOISE_BAND)
    .sort((a, b) => (b.month_delta ?? 0) - (a.month_delta ?? 0));
}

/** "You're up 6 this month." / "You're steady this month." / absent.
 *
 * null when there is no month to compare against — a student in their first
 * weeks is told so by the caller rather than being handed a fabricated zero. */
export function movementSentence(delta: number | null): string | null {
  if (delta === null) return null;
  if (Math.abs(delta) <= MOVEMENT_NOISE_BAND) return "You're steady this month.";
  if (delta > 0) return `You're up ${Math.round(delta)} this month.`;
  return `You're down ${Math.round(Math.abs(delta))} this month.`;
}

export type Gap = "above" | "below" | "equal";

/**
 * How the predicted grade sits against the averaging grade — the story Progress
 * exists to tell (§3.3).
 *
 * null when either side is missing: a student with no marked work has no
 * average, and rendering the two as equal would claim their record matches a
 * prediction drawn from nothing (PROD-2).
 *
 * The comparison is made on the *grades* first, because those are what the
 * screen shows. Two scores either side of a boundary display as different
 * grades and get the sentence explaining the gap; two scores four points apart
 * inside one grade display as the same grade and get "matches", which is what
 * the reader can see. Only once the grades differ do the scores decide the
 * direction — they are mapped through the same boundary list, so they cannot
 * disagree with the grades about which is higher.
 */
export function gradeGap(subject: SubjectReadiness): Gap | null {
  const { predicted_grade, averaging_grade, score, averaging_score } = subject;
  if (predicted_grade === null || averaging_grade === null) return null;
  if (predicted_grade === averaging_grade) return "equal";
  if (score === null || averaging_score === null) return null;
  return score > averaging_score ? "above" : score < averaging_score ? "below" : "equal";
}

/** The sentence for each gap (copy §4.5). One string per row of that table, so
    a change to the wording happens once. */
export const GAP_SENTENCE: Record<Gap, string> = {
  above:
    "You're tracking above your recent average — the last three pieces have been stronger than the ones before.",
  below:
    "Your recent work has been weaker than your record — the last three pieces pulled the estimate down.",
  equal: "Your recent work matches your record.",
};
