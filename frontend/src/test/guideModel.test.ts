import { expect, test } from "vitest";
import { WORKSPACE_STEPS, guideModel } from "../tutor/onboarding/guideModel";
import type { OnboardingState } from "../api/onboarding";

const item = (key: string, state: string, kind = "defaulted") => ({ key, kind, state });

/** A later member whose own class is waiting for its timetable. */
function member(isOwner: boolean) {
  return {
    complete: false,
    in_flow: true,
    is_owner: isOwner,
    account: item("account_basics", "default"),
    subjects: [
      {
        subject_id: 7,
        subject_name: "Chemistry",
        required: [{ key: "syllabus", done: true }],
        items: [
          item("boundaries", "not_set"),
          item("marking_rules", "default"),
          item("mistake_categories", "default"),
          item("weak_threshold", "default"),
          item("teaching_guidance", "not_set", "optional"),
        ],
        reviewed_count: 0,
        review_total: 4,
        classes: [
          {
            group_id: 11,
            group_name: "Y10",
            complete: false,
            steps: [
              { key: "timetable", done: false },
              { key: "taught_before", done: false },
              { key: "plan_inputs", done: false },
              { key: "plan_accepted", done: false },
            ],
          },
        ],
      },
    ],
    next_step: { key: "timetable", subject_id: 7, group_id: 11 },
  } as unknown as OnboardingState;
}

test("a later member's model has no workspace step", () => {
  const model = guideModel(member(false), () => false);
  expect(model.steps.some((s) => WORKSPACE_STEPS.includes(s.id))).toBe(false);
  expect(model.defaultOpen).toBe("timetable");
  expect(guideModel(member(true), () => false).steps.length).toBeGreaterThan(model.steps.length);
});

test("putting aside the next step never points at a workspace step", () => {
  const model = guideModel(member(false), (key) => key === "setup_step:timetable:11");
  expect(model.defaultOpen === null || !WORKSPACE_STEPS.includes(model.defaultOpen)).toBe(true);
});

test("with every visible step put aside the guide is allSkipped", () => {
  const model = guideModel(
    member(false),
    // Only the member's own steps are put aside; a hidden workspace step must not matter.
    (key) => key.startsWith("setup_step:") && !/account|boundaries|defaults|guidance/.test(key),
  );
  expect(model.allSkipped).toBe(true);
});
