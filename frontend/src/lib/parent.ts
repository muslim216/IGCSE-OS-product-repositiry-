import type { SubjectReadiness } from "../api/readiness";
import { countWord } from "./verdict";

/* The parent screen's sentences, derived rather than written inline.

   This copy is read by people who cannot ask a follow-up question, who visit
   rarely, and who read ambiguity as bad news that then lands on the child. Every
   rule below exists because of that reader.

   **No gendered pronoun, anywhere.** No gender is stored on `User`, and
   inferring one from a name misgenders real people. The child's name or a bare
   plural does the work: "on track in 3 of 4 subjects", never "3 of her 4
   subjects". The design spec's own §6 mock uses "her"; that is a mock, and this
   rule governs (copy §4.1.3).

   **Counts up to ten are words in prose.** "all four subjects", not "all 4". */

/** Subjects with a readiness band. A subject with no marked work has no band,
    and is neither on track nor in trouble — it is simply not yet measured, and
    counting it either way would be a claim (PROD-2). */
export function bandedSubjects(subjects: SubjectReadiness[]): SubjectReadiness[] {
  return subjects.filter((s) => s.status !== null);
}

/**
 * The verdict sentence — the first thing read, and for many parents the only
 * thing read (copy §4.6).
 *
 * Evaluated top to bottom, first match wins. Every branch ends in a full stop:
 * a verdict without one reads as a label rather than an answer.
 */
export function parentVerdict(name: string, subjects: SubjectReadiness[]): string {
  const banded = bandedSubjects(subjects);
  if (banded.length === 0) {
    return `There isn't enough marked work yet to say how ${name} is doing.`;
  }
  const onTrack = banded.filter((s) => s.status === "on_track").length;
  if (onTrack === banded.length) {
    return `${name} is on track in all ${countWord(banded.length)} subjects.`;
  }
  if (onTrack === 0) {
    return `${name} needs support in ${countWord(banded.length)} of ${countWord(banded.length)} subjects.`;
  }
  // Counts up to ten are words in prose (§4.1), so both numbers spell out:
  // "one of two", not "1 of 2".
  return `${name} is on track in ${countWord(onTrack)} of ${countWord(banded.length)} subjects.`;
}

/** Where the verdict came from. Every number on this screen is traceable to the
    work it was computed from (PROD-1), and a parent who is told a grade without
    being told what it rests on reads it as a commitment. */
export function provenance(subjects: SubjectReadiness[]): string {
  const pieces = subjects.reduce((sum, s) => sum + s.marked_piece_count, 0);
  if (pieces === 0) return "No marked work yet";
  return `Based on ${pieces} marked ${pieces === 1 ? "piece" : "pieces"} · updated weekly`;
}

/**
 * WHAT YOU CAN DO — required in every state, including, and especially, when
 * the answer is nothing.
 *
 * A parent visits rarely, cannot act on most of what they see, and reads
 * ambiguity as bad news. A screen that ends without saying whether anything is
 * required of them manufactures exactly the anxiety it exists to prevent. So
 * this never returns null.
 *
 * It also never asks the parent to chase the child. Spec §2.3: no surface
 * offers an action that requires another person to respond, and turning the
 * parent screen into a to-do list aimed at a teenager damages the relationship
 * the tutor depends on.
 */
export function whatYouCanDo(subjects: SubjectReadiness[]): string {
  const anyMarked = subjects.some((s) => s.marked_piece_count > 0);
  if (!anyMarked) {
    return "There's nothing to do yet. Work appears here as their tutor marks it.";
  }
  return "Nothing is needed right now. We'll tell you if that changes.";
}
