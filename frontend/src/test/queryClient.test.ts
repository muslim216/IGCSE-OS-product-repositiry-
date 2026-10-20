import { afterEach, expect, test, vi } from "vitest";
import { FOCUS_STALE_MS, createQueryClient, refetchOnFocusIfStale } from "../lib/queryClient";

/* Coming back to the tab refetched every query on the page however fresh it
   was; now only data older than FOCUS_STALE_MS is asked for again. */

afterEach(() => vi.useRealTimers());

test("fresh data is not refetched on focus, stale data is", () => {
  vi.useFakeTimers();
  const now = Date.now();
  expect(refetchOnFocusIfStale({ state: { dataUpdatedAt: now } } as never)).toBe(false);
  expect(
    refetchOnFocusIfStale({ state: { dataUpdatedAt: now - FOCUS_STALE_MS - 1 } } as never),
  ).toBe(true);
  // Never loaded: refetch.
  expect(refetchOnFocusIfStale({ state: { dataUpdatedAt: 0 } } as never)).toBe(true);
});

test("the app's client uses it by default", () => {
  const client = createQueryClient();
  expect(client.getDefaultOptions().queries?.refetchOnWindowFocus).toBe(refetchOnFocusIfStale);
});
