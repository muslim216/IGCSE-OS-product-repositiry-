import type { TodayView } from "../api/today";

/* The tutor's verdict — the one sentence that answers "does anything need me?".
   Pure derivation so the composition rules are unit-testable and live in exactly
   one place rather than being re-derived inside JSX. */

/** Counts up to ten are words in prose, digits in chips and counters (copy §4.1).
    Beyond ten a digit reads faster than a word in either place. */
const WORDS = [
  "zero",
  "one",
  "two",
  "three",
  "four",
  "five",
  "six",
  "seven",
  "eight",
  "nine",
  "ten",
] as const;

export function countWord(n: number): string {
  return n >= 0 && n <= 10 ? WORDS[n] : String(n);
}

function capitalize(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

function plural(n: number, one: string, many: string): string {
  return n === 1 ? one : many;
}

/**
 * Line 1, evaluated top to bottom — first match wins (copy §4.2). Every branch
 * ends in a full stop: a verdict without one reads as a label, not a sentence.
 */
export function verdictLine1(view: TodayView): string {
  if (view.class_count === 0) return "You haven't set up a class yet.";
  if (view.joined_student_count === 0) return "No students have joined yet.";
  if (view.classes_with_evidence === 0) return "Nothing marked yet.";

  const atRisk = view.classes.filter((c) => c.status === "at_risk").length;
  if (atRisk > 0) {
    return `${capitalize(countWord(atRisk))} ${plural(atRisk, "class needs", "classes need")} attention.`;
  }
  const needsAttention = view.classes.filter((c) => c.status === "needs_attention").length;
  if (needsAttention > 0) {
    return `${capitalize(countWord(needsAttention))} ${plural(
      needsAttention,
      "class could",
      "classes could",
    )} use a look.`;
  }
  return "Your classes are running well.";
}

/**
 * Line 2: clauses joined by " · ", each omitted when its count is zero (copy
 * §4.3). A clause whose count is zero is never rendered as "0" — if every clause
 * is zero the line itself is absent and the section terminal carries the meaning.
 */
export function verdictLine2(view: TodayView): string | null {
  const clauses: string[] = [];
  const lessons = view.lessons.length;
  if (lessons === 1) clauses.push("One lesson today");
  else if (lessons > 1) clauses.push(`${capitalize(countWord(lessons))} lessons today`);

  const review = view.review_count;
  if (review === 1) clauses.push("one piece to mark");
  else if (review > 1) clauses.push(`${countWord(review)} pieces to mark when you have a moment`);

  return clauses.length > 0 ? clauses.join(" · ") : null;
}

/** True when the whole surface is clear, so the day can end with a sentence
    rather than a screen of empty panels (copy §4.4, UX-29). */
export function isClearDay(view: TodayView): boolean {
  return (
    view.class_count > 0 &&
    view.lessons.length === 0 &&
    view.review_count === 0 &&
    view.classes.every((c) => c.status === "on_track" || c.status === null)
  );
}

/** Coverage as the `9/11` pair, or null when the class has nobody in it — a
    coverage chip on an empty class is noise, and the row says "no students" instead. */
export function coverageLabel(row: { students_with_evidence: number; member_count: number }) {
  if (row.member_count === 0) return null;
  return `${row.students_with_evidence}/${row.member_count}`;
}
