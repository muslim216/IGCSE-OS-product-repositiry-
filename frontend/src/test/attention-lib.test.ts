import { expect, test } from "vitest";
import { attentionHref } from "../lib/attention";

/* Where each kind of to-do item is dealt with. Today and Review both link
   through this, so one wrong branch would be wrong on both. */

const base = {
  assignment_id: null,
  past_paper_id: null,
  assignment_title: "x",
  reason: "extraction_failed",
  detail: null,
  submission_id: null,
  student_name: null,
};

test("a submission opens its marking review", () => {
  expect(attentionHref({ ...base, assignment_id: 2, submission_id: 8, reason: "ai_failed" })).toBe(
    "/tutor/submissions/8",
  );
});

test("an unreadable past paper opens the shelf at that paper", () => {
  expect(attentionHref({ ...base, past_paper_id: 9 })).toBe("/tutor/past-papers#paper-9");
});

test("homework whose questions couldn't be read opens the homework", () => {
  expect(attentionHref({ ...base, assignment_id: 3 })).toBe("/tutor/assignments/3");
});
