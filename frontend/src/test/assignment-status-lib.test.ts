import { expect, test } from "vitest";
import { assignmentStatus } from "../lib/assignmentStatus";

/* One status map for the homework list and the assignment page. A screen's
   own wording for a status is an override at its call site, and reaches no
   other status. */

test("each status reads in words, and an unknown one as work in progress", () => {
  expect(assignmentStatus("extracting").label).toBe("Reading the paper…");
  expect(assignmentStatus("review").label).toBe("Check the questions");
  expect(assignmentStatus("something_new").label).toBe("In progress");
});

test("an override changes only the label of the status it names", () => {
  const labels = { review: "Check the questions, then publish" };
  expect(assignmentStatus("review", labels)).toEqual({
    label: "Check the questions, then publish",
    classes: assignmentStatus("review").classes,
  });
  expect(assignmentStatus("closed", labels).label).toBe("Closed");
});
