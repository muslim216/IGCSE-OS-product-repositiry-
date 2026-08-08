import { expect, test } from "vitest";
import { ABSENT, REASON_LABELS } from "../lib/labels";

/* The reason strings the backend actually sends, read from
   backend/app/api/assignments.py: "extraction_failed" for a stuck assignment,
   and the three Submission statuses that endpoint filters to. This list is the
   contract; nothing checks the two agree at build time (RISK-6), so it is
   asserted here. */
const BACKEND_REASONS = ["extraction_failed", "ai_failed", "ai_marked", "needs_review"];

test("every backend reason has a label", () => {
  for (const reason of BACKEND_REASONS) {
    expect(REASON_LABELS[reason], `no label for "${reason}"`).toBeTruthy();
  }
});

test("no label is a raw enum string leaking to the tutor", () => {
  // The bug this file exists for: needs_review was missing from the copy the
  // tutor's home imported, so the most common reason rendered as its enum.
  for (const [reason, label] of Object.entries(REASON_LABELS)) {
    expect(label).not.toBe(reason);
    expect(label).not.toMatch(/_/);
  }
});

test("the map carries no reason the backend cannot send", () => {
  expect(Object.keys(REASON_LABELS).sort()).toEqual([...BACKEND_REASONS].sort());
});

test("absent states are words, never a zero or a bare symbol", () => {
  for (const value of Object.values(ABSENT)) {
    expect(value.trim()).not.toBe("");
    expect(value).not.toMatch(/^[0-—–-]+$/);
    expect(value).toMatch(/[a-z]/i);
  }
});
