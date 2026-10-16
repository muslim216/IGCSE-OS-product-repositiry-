import { expect, test } from "vitest";
import {
  MARKING_POLL_FAST_FOR_MS,
  MARKING_POLL_FAST_MS,
  MARKING_POLL_SLOW_MS,
  MARKING_POLL_STOP_AFTER_MS,
  markingPollInterval,
} from "../lib/markingPoll";

/* A student page waiting for marks used to ask every 4 seconds for as long as
   the tab stayed open, which for work waiting on the tutor could be days. */

test("checks quickly at first, while the AI usually answers", () => {
  expect(markingPollInterval(0)).toBe(MARKING_POLL_FAST_MS);
  expect(markingPollInterval(MARKING_POLL_FAST_FOR_MS - 1)).toBe(MARKING_POLL_FAST_MS);
});

test("then slowly", () => {
  expect(markingPollInterval(MARKING_POLL_FAST_FOR_MS)).toBe(MARKING_POLL_SLOW_MS);
  expect(markingPollInterval(MARKING_POLL_STOP_AFTER_MS - 1)).toBe(MARKING_POLL_SLOW_MS);
});

test("then not at all", () => {
  expect(markingPollInterval(MARKING_POLL_STOP_AFTER_MS)).toBe(false);
  expect(markingPollInterval(7 * 24 * 60 * 60_000)).toBe(false);
});

test("a forgotten tab asks a bounded number of times", () => {
  // Simulates a week-long open tab; capped so a rule that never stops fails
  // here instead of hanging the suite.
  let waited = 0;
  let asks = 0;
  while (asks < 10_000) {
    const next = markingPollInterval(waited);
    if (next === false) break;
    waited += next;
    asks += 1;
  }
  expect(asks).toBeLessThan(100);
});
