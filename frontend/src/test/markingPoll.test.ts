import { renderHook } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import {
  MARKING_POLL_FAST_FOR_MS,
  MARKING_POLL_FAST_MS,
  MARKING_POLL_SLOW_MS,
  MARKING_POLL_STOP_AFTER_MS,
  markingPollInterval,
  useMarkingRefetchInterval,
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

afterEach(() => vi.useRealTimers());

const waiting = { state: { data: { status: "being_marked" } } };
const marked = { state: { data: { status: "marked" } } };

test("the clock starts when the page first sees being marked", () => {
  vi.useFakeTimers();
  const { result } = renderHook(({ key }) => useMarkingRefetchInterval(key), {
    initialProps: { key: 1 },
  });
  expect(result.current(waiting)).toBe(MARKING_POLL_FAST_MS);
  vi.advanceTimersByTime(MARKING_POLL_STOP_AFTER_MS);
  expect(result.current(waiting)).toBe(false);
});

test("anything other than being marked stops polling and resets the clock", () => {
  vi.useFakeTimers();
  const { result } = renderHook(() => useMarkingRefetchInterval(1));
  result.current(waiting);
  vi.advanceTimersByTime(MARKING_POLL_STOP_AFTER_MS);
  expect(result.current(marked)).toBe(false);
  // A fresh hand-in on the same page polls quickly again.
  expect(result.current(waiting)).toBe(MARKING_POLL_FAST_MS);
  expect(result.current({ state: { data: null } })).toBe(false);
});

test("moving on to other work starts its own clock", () => {
  vi.useFakeTimers();
  const { result, rerender } = renderHook(({ key }) => useMarkingRefetchInterval(key), {
    initialProps: { key: 1 },
  });
  result.current(waiting);
  vi.advanceTimersByTime(MARKING_POLL_STOP_AFTER_MS);
  expect(result.current(waiting)).toBe(false);

  rerender({ key: 2 });
  expect(result.current(waiting)).toBe(MARKING_POLL_FAST_MS);
});
