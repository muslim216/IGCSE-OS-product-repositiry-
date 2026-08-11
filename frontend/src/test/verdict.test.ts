import { expect, test } from "vitest";
import type { TodayView } from "../api/today";
import { countWord, coverageLabel, isClearDay, verdictLine1, verdictLine2 } from "../lib/verdict";

function view(over: Partial<TodayView> = {}): TodayView {
  return {
    classes: [],
    lessons: [],
    review_count: 0,
    class_count: 1,
    joined_student_count: 10,
    classes_with_evidence: 1,
    ...over,
  };
}

function cls(status: TodayView["classes"][number]["status"], name = "C") {
  return {
    group_id: Math.random(),
    name,
    subject_name: "Physics",
    score: 60,
    predicted_grade: "5",
    status,
    boundaries_missing: false,
    member_count: 10,
    students_with_evidence: 10,
    awaiting_review_count: 0,
  };
}

const lesson = {
  id: 1,
  group_id: 1,
  group_name: "A",
  subject_name: "Physics",
  weekday: 1,
  start_time: "16:00:00",
  duration_min: 60,
  title: null,
};

test("counts up to ten are words, beyond that digits", () => {
  expect(countWord(1)).toBe("one");
  expect(countWord(10)).toBe("ten");
  expect(countWord(11)).toBe("11");
});

test("verdict line 1 matches top to bottom, first match winning", () => {
  expect(verdictLine1(view({ class_count: 0 }))).toBe("You haven't set up a class yet.");
  expect(verdictLine1(view({ joined_student_count: 0 }))).toBe("No students have joined yet.");
  expect(verdictLine1(view({ classes_with_evidence: 0 }))).toBe("Nothing marked yet.");
  expect(verdictLine1(view({ classes: [cls("at_risk")] }))).toBe("One class needs attention.");
  expect(verdictLine1(view({ classes: [cls("at_risk"), cls("at_risk")] }))).toBe(
    "Two classes need attention.",
  );
  expect(verdictLine1(view({ classes: [cls("needs_attention")] }))).toBe(
    "One class could use a look.",
  );
  expect(verdictLine1(view({ classes: [cls("on_track")] }))).toBe("Your classes are running well.");
});

test("at risk outranks needs attention", () => {
  const v = view({ classes: [cls("needs_attention"), cls("at_risk")] });
  expect(verdictLine1(v)).toBe("One class needs attention.");
});

test("every verdict ends in a full stop, so it reads as a sentence not a label", () => {
  for (const v of [
    view({ class_count: 0 }),
    view({ classes: [cls("at_risk")] }),
    view({ classes: [cls("on_track")] }),
  ]) {
    expect(verdictLine1(v).endsWith(".")).toBe(true);
  }
});

test("a zero clause is omitted, never rendered as 0", () => {
  expect(verdictLine2(view({ lessons: [lesson], review_count: 0 }))).toBe("One lesson today");
  expect(verdictLine2(view({ lessons: [], review_count: 1 }))).toBe("one piece to mark");
  expect(verdictLine2(view({ lessons: [lesson, { ...lesson, id: 2 }], review_count: 2 }))).toBe(
    "Two lessons today · two pieces to mark when you have a moment",
  );
});

test("both clauses zero means the line itself is absent", () => {
  expect(verdictLine2(view({ lessons: [], review_count: 0 }))).toBeNull();
});

test("a clear day needs classes, no lessons, no review and nothing off track", () => {
  expect(isClearDay(view({ classes: [cls("on_track")] }))).toBe(true);
  expect(isClearDay(view({ classes: [cls("at_risk")] }))).toBe(false);
  expect(isClearDay(view({ classes: [cls("on_track")], review_count: 1 }))).toBe(false);
  expect(isClearDay(view({ classes: [cls("on_track")], lessons: [lesson] }))).toBe(false);
  // No classes at all is not a "clear day" — it is a cold start.
  expect(isClearDay(view({ class_count: 0 }))).toBe(false);
});

test("coverage renders as a pair, and is absent for an empty class", () => {
  expect(coverageLabel({ students_with_evidence: 9, member_count: 11 })).toBe("9/11");
  expect(coverageLabel({ students_with_evidence: 0, member_count: 0 })).toBeNull();
});
