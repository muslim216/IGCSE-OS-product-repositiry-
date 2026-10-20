import { useCallback, useRef } from "react";

/**
 * How a student's page waits for marks while its work is "being marked".
 *
 * It used to ask every 4 seconds for as long as the tab stayed open. "Being
 * marked" also covers work waiting on the tutor (the AI was unsure, or could
 * not mark it), which can take days, so one forgotten tab asked the server
 * 900 times an hour, and a marking outage multiplied that by every student
 * waiting (audit finding OPS-08). Now: quickly at first, while the AI usually
 * answers; then slowly; then not at all. Coming back to the tab still checks
 * (the app refetches on focus any data older than 30 s, `lib/queryClient.ts`),
 * so nothing is missed.
 */
export const MARKING_POLL_FAST_MS = 4_000;
export const MARKING_POLL_FAST_FOR_MS = 2 * 60_000;
export const MARKING_POLL_SLOW_MS = 30_000;
export const MARKING_POLL_STOP_AFTER_MS = 30 * 60_000;

/** The wait before the next check, given how long this page has waited. */
export function markingPollInterval(waitedMs: number): number | false {
  if (waitedMs < MARKING_POLL_FAST_FOR_MS) return MARKING_POLL_FAST_MS;
  if (waitedMs < MARKING_POLL_STOP_AFTER_MS) return MARKING_POLL_SLOW_MS;
  return false;
}

/**
 * A `refetchInterval` that polls on the schedule above while `inProgress` names
 * something in the query's data still in progress, and stops for anything
 * else. `inProgress` returns `false` for "nothing", or a string naming what is
 * in progress. The clock starts the first time the page sees work in progress
 * and restarts when that name changes (a new hand-in joins one that is stuck)
 * or the page moves on to other work (`key`); it resets on "nothing", so fresh
 * work always polls quickly again. Pass a module-level `inProgress`, so the
 * callback keeps one identity across renders.
 */
export function useBackoffRefetchInterval(
  key: number,
  inProgress: (data: unknown) => string | false,
) {
  const clock = useRef<{ key: number; what: string; since: number } | null>(null);
  // `unknown`, so this callback never steers how the page's query data is
  // typed; the predicate reads it defensively instead.
  return useCallback(
    (query: { state: { data?: unknown } }): number | false => {
      const what = inProgress(query.state.data);
      if (what === false) {
        clock.current = null;
        return false;
      }
      if (clock.current?.key !== key || clock.current.what !== what) {
        clock.current = { key, what, since: Date.now() };
      }
      return markingPollInterval(Date.now() - clock.current.since);
    },
    [key, inProgress],
  );
}

function beingMarked(data: unknown): string | false {
  const status = (data as { status?: string } | null | undefined)?.status;
  return status === "being_marked" ? status : false;
}

/** The student pages: their data carries the student-facing `status`. */
export function useMarkingRefetchInterval(key: number) {
  return useBackoffRefetchInterval(key, beingMarked);
}
