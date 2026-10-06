import type { OnboardingState } from "../../api/onboarding";

/**
 * What the setup guide shows and in what order, as pure functions of the
 * server's onboarding state plus which steps the tutor has put aside with "Not
 * now" (owner decision 2026-10-06).
 *
 * The server still decides what is done and which step is next (`SEC-10`);
 * nothing here is stored on it. Skipping is a display choice layered on top: a
 * skipped step counts as out of the way, so the guide moves to the next one, and
 * when nothing is left that the tutor has not put aside the guide is not shown.
 * It lives apart from the component because the Overview needs the same answer
 * to decide whether to show the guide at all.
 */

export type StepId =
  | "account"
  | "syllabus"
  | "boundaries"
  | "defaults"
  | "guidance"
  | "timetable"
  | "taught_before"
  | "plan_inputs"
  | "plan_accepted";

export type Marker = "Required" | "Optional" | "Can wait";

export const STEPS: { id: StepId; name: string; marker: Marker }[] = [
  { id: "account", name: "Time zone and weekly summary", marker: "Can wait" },
  { id: "syllabus", name: "Syllabus", marker: "Required" },
  { id: "boundaries", name: "Grade boundaries", marker: "Can wait" },
  { id: "defaults", name: "Avora's marking defaults", marker: "Can wait" },
  { id: "guidance", name: "Teaching guidance", marker: "Optional" },
  { id: "timetable", name: "Class and timetable", marker: "Required" },
  { id: "taught_before", name: "Where this class is up to", marker: "Required" },
  { id: "plan_inputs", name: "Plan details", marker: "Required" },
  { id: "plan_accepted", name: "Accept the teaching plan", marker: "Required" },
];

export const SUBJECT_STEPS: StepId[] = ["boundaries", "defaults", "guidance", "timetable"];
export const CLASS_STEPS: StepId[] = ["taught_before", "plan_inputs", "plan_accepted"];
export const DEFAULT_ROWS = ["marking_rules", "mistake_categories", "weak_threshold"] as const;

/** The key for the whole guide. */
export const GUIDE_KEY = "setup_guide";

export const stepName = (id: StepId) => STEPS.find((s) => s.id === id)!.name;
const isStepId = (key: string | undefined): key is StepId =>
  key === "syllabus" || CLASS_STEPS.includes(key as StepId) || key === "timetable";

export function guideModel(data: OnboardingState, isHidden: (key: string) => boolean) {
  const next = data.next_step;
  const subject = data.subjects.find((s) => s.subject_id === next?.subject_id);
  const klass = subject?.classes.find((c) => c.group_id === next?.group_id);
  const syllabusDone = data.subjects.some((s) =>
    s.required.some((r) => r.key === "syllabus" && r.done),
  );
  const subjectReady = !!subject && subject.required.some((r) => r.key === "syllabus" && r.done);
  const classDone = (key: string) => klass?.steps.find((s) => s.key === key)?.done ?? false;
  const nextId: StepId | null = isStepId(next?.key) ? (next?.key as StepId) : null;
  const itemState = (key: string) => subject?.items.find((i) => i.key === key)?.state;

  const isDone = (id: StepId): boolean => {
    if (id === "syllabus") return syllabusDone;
    if (id === "timetable" || CLASS_STEPS.includes(id)) return classDone(id);
    return false;
  };

  /** Nothing is being asked for: done, or already set or reviewed. The four
   *  optional-ish steps have no "done" flag of their own, only item states. */
  const settled = (id: StepId): boolean => {
    if (isDone(id)) return true;
    if (id === "account") return data.account.state !== "default";
    if (id === "boundaries") return !!subject && itemState("boundaries") !== "not_set";
    if (id === "guidance") return !!subject && itemState("teaching_guidance") !== "not_set";
    if (id === "defaults") {
      return (
        !!subject &&
        DEFAULT_ROWS.every((k) => {
          const state = itemState(k);
          return state === "reviewed" || state === "set_by_you";
        })
      );
    }
    return false;
  };

  /** What an undone earlier step costs: the line shown instead of opening. */
  const needs = (id: StepId): string | null => {
    if (SUBJECT_STEPS.includes(id) && !subjectReady) return "Add the syllabus first";
    if (id === "taught_before" && !(klass && classDone("timetable")))
      return "Add the class and its timetable first";
    if (id === "plan_inputs" && !(klass && classDone("taught_before")))
      return "Say where this class is up to first";
    if (id === "plan_accepted" && !(klass && classDone("plan_inputs")))
      return "Enter the plan details first";
    return null;
  };

  /** Names the step and, where it belongs to one, its subject or class, so
   *  skipping Boundaries for Chemistry never skips it for Physics. Null when the
   *  step has no subject or class to belong to yet (it is locked then). */
  const keyOf = (id: StepId): string | null => {
    if (id === "account" || id === "syllabus") return `setup_step:${id}`;
    // Before the class exists the timetable step is the form that creates it, so
    // it is keyed by the subject; once there is a class it is that class's.
    if (id === "timetable") {
      if (klass) return `setup_step:timetable:${klass.group_id}`;
      return subject ? `setup_step:timetable:subject-${subject.subject_id}` : null;
    }
    if (SUBJECT_STEPS.includes(id))
      return subject ? `setup_step:${id}:${subject.subject_id}` : null;
    return klass ? `setup_step:${id}:${klass.group_id}` : null;
  };
  const skipped = (id: StepId): boolean => {
    const key = keyOf(id);
    return key !== null && !settled(id) && isHidden(key);
  };
  /** Something the guide still asks of the tutor: not done, not put aside, and
   *  not waiting on an earlier step. */
  const actionable = (id: StepId): boolean => !settled(id) && !skipped(id) && !needs(id);

  const skippedKeys = STEPS.filter((s) => skipped(s.id)).flatMap((s) => keyOf(s.id) ?? []);
  const anySkipped = STEPS.some((s) => skipped(s.id));
  const anyActionable = STEPS.some((s) => actionable(s.id));
  /** Every remaining step has been put aside (or waits on one that has). */
  const allSkipped = anySkipped && !anyActionable;

  /** The server's step, unless the tutor skipped it, then the first thing left. */
  const defaultOpen: StepId | null =
    nextId === null
      ? null
      : !skipped(nextId)
        ? nextId
        : (STEPS.find((s) => actionable(s.id))?.id ?? null);

  return {
    subject,
    klass,
    nextId,
    defaultOpen,
    isDone,
    settled,
    needs,
    keyOf,
    skipped,
    actionable,
    allSkipped,
    skippedKeys,
  };
}

/** Whether the Overview should leave the guide out: the tutor said "Not now" to
 *  all of it, or has put aside every step that was left. */
export function guideIsGone(data: OnboardingState, isHidden: (key: string) => boolean): boolean {
  return isHidden(GUIDE_KEY) || guideModel(data, isHidden).allSkipped;
}
