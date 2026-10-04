import type { SubjectReadiness } from "../api/readiness";
import { countWord } from "./verdict";
import { measuredBySeverity } from "./studentVerdict";

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
  return subjects.filter((s) => s.verdict.status !== "not_enough_data");
}

/** "Chemistry" / "Chemistry and Biology" — only ever called with one or two. */
function joinNames(subjects: SubjectReadiness[]): string {
  return subjects.map((s) => s.subject_name).join(" and ");
}

/**
 * The verdict sentence — the first thing read, and for many parents the only
 * thing read (copy §4.6).
 *
 * Evaluated top to bottom, first match wins. Every branch ends in a full stop:
 * a verdict without one reads as a label rather than an answer.
 *
 * **One or two measured subjects are named, not counted.** Applied literally,
 * the copy deck's counting template produced "needs attention in one of one
 * subjects" and "on track in all two subjects" — sentences no person writes,
 * and on the screen a worried parent reads most closely. Naming the subject is
 * both shorter and more useful. From three up the count reads naturally.
 *
 * **Unmeasured subjects are outside the count, and the sentence says so** when
 * any exist: "on track in all three subjects with marked work". Without the
 * qualifier a parent looking at four subject rows would read "all three" as an
 * arithmetic slip, or as the fourth having been forgotten.
 */
export function parentVerdict(name: string, subjects: SubjectReadiness[]): string {
  const banded = bandedSubjects(subjects);
  if (banded.length === 0) {
    return `There isn't enough marked work yet to say how ${name} is doing.`;
  }
  const onTrack = banded.filter((s) => s.verdict.status === "on_track");
  const notOnTrack = banded.filter((s) => s.verdict.status !== "on_track");

  if (banded.length <= 2) {
    if (notOnTrack.length === 0) return `${name} is on track in ${joinNames(onTrack)}.`;
    if (onTrack.length === 0) return `${name} needs attention in ${joinNames(notOnTrack)}.`;
    return `${name} is on track in ${joinNames(onTrack)} but needs attention in ${joinNames(notOnTrack)}.`;
  }

  const scope = banded.length < subjects.length ? " with marked work" : "";
  const total = countWord(banded.length);
  if (notOnTrack.length === 0) return `${name} is on track in all ${total} subjects${scope}.`;
  if (onTrack.length === 0) return `${name} needs attention in all ${total} subjects${scope}.`;
  // Counts up to ten are words in prose (§4.1), so both numbers spell out:
  // "three of four", not "3 of 4".
  return `${name} is on track in ${countWord(onTrack.length)} of ${total} subjects${scope}.`;
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
  // The most urgent subject's next step — the same one the tutor and the
  // student are shown, so a parent is never told "nothing is needed" about a
  // child the tutor has flagged (coherence C.1).
  const urgent = measuredBySeverity(subjects).find((s) => s.verdict.status !== "on_track");
  if (urgent) return `${urgent.subject_name}: ${urgent.verdict.next_step}`;
  // "Nothing is needed" is a claim about measured subjects only: it needs at
  // least one, and every one of them on track (PROD-2).
  const banded = bandedSubjects(subjects);
  if (banded.length === 0) {
    return "There isn't enough marked work yet to say whether anything is needed.";
  }
  const unmeasured = subjects.filter((s) => s.verdict.status === "not_enough_data");
  if (unmeasured.length > 0) {
    const measured = banded.map((s) => s.subject_name).join(" and ");
    const names = unmeasured.map((s) => s.subject_name).join(" and ");
    const verb = unmeasured.length === 1 ? "isn't" : "aren't";
    return `Nothing is needed right now in ${measured}. ${names} ${verb} measured yet.`;
  }
  return "Nothing is needed right now. We'll tell you if that changes.";
}
