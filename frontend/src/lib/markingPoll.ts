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
 * at once (TanStack Query refetches on window focus), so nothing is missed.
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
 * A `refetchInterval` for a query whose data carries the student-facing
 * `status`. The clock starts the first time the page sees "being marked" for
 * this piece of work (`key`) and resets when it sees anything else, or when
 * the same page moves on to other work, so a fresh hand-in polls quickly
 * again.
 */
export function useMarkingRefetchInterval(key: number) {
  const clock = useRef<{ key: number; since: number } | null>(null);
  // `unknown`, so this callback never steers how the page's query data is
  // typed; the status is read defensively instead.
  return useCallback(
    (query: { state: { data?: unknown } }): number | false => {
      const data = query.state.data as { status?: string } | null | undefined;
      if (data?.status !== "being_marked") {
        clock.current = null;
        return false;
      }
      if (clock.current?.key !== key) clock.current = { key, since: Date.now() };
      return markingPollInterval(Date.now() - clock.current.since);
    },
    [key],
  );
}
