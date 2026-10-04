import { expect, test } from "vitest";
import { measuredBySeverity, wordingFor, type StudentVerdict } from "../lib/studentVerdict";

const attention: StudentVerdict = {
  status: "needs_attention",
  reason_topics: ["Ionic bonding", "Moles"],
  next_step: "Weakest right now: Ionic bonding and Moles.",
};
const onTrack: StudentVerdict = { status: "on_track", reason_topics: [], next_step: "Keep going." };
const none: StudentVerdict = { status: "not_enough_data", reason_topics: [], next_step: "x" };

test("tutor and parent read the same line", () => {
  expect(wordingFor("tutor", attention).line).toBe("Needs attention: Ionic bonding, Moles");
  expect(wordingFor("parent", attention).line).toBe(wordingFor("tutor", attention).line);
  expect(wordingFor("tutor", onTrack).line).toBe("On track");
});

test("the student's wording is kinder but names the same topics", () => {
  expect(wordingFor("student", attention).line).toBe("Focus on: Ionic bonding, Moles");
  expect(wordingFor("student", onTrack).line).toBe("You're on track");
  expect(wordingFor("student", attention).reason).toBe(wordingFor("tutor", attention).reason);
  expect(wordingFor("student", attention).nextStep).toBe(wordingFor("tutor", attention).nextStep);
});

test("at risk keeps its status for adults and is never a bare alarm for a student", () => {
  const risk: StudentVerdict = { ...attention, status: "at_risk" };
  expect(wordingFor("tutor", risk).line).toBe("At risk: Ionic bonding, Moles");
  expect(wordingFor("student", risk).line).toBe("Focus on: Ionic bonding, Moles");
});

test("a status with no topics still says something, per role", () => {
  const bare = { ...attention, reason_topics: [] };
  expect(wordingFor("parent", bare).line).toBe("Needs attention");
  expect(wordingFor("student", bare).line).toBe("Worth a closer look");
});

test("no data is said as absence for every role", () => {
  for (const role of ["tutor", "student", "parent"] as const) {
    expect(wordingFor(role, none).line).toBe("Not enough data yet");
  }
});

test("severity ordering excludes subjects with no verdict", () => {
  const rows = [
    { n: "a", verdict: onTrack },
    { n: "b", verdict: none },
    { n: "c", verdict: attention },
    { n: "d", verdict: { ...attention, status: "at_risk" as const } },
  ];
  expect(measuredBySeverity(rows).map((r) => r.n)).toEqual(["d", "c", "a"]);
});
