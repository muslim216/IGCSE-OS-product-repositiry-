import { QueryClient, type Query } from "@tanstack/react-query";
import { shouldRetry } from "./errors";

/** How old data must be before coming back to the tab refetches it. */
export const FOCUS_STALE_MS = 30_000;

/**
 * Coming back to the tab used to refetch every query on the page, however
 * fresh, so a student flicking between tabs re-asked for everything each time
 * (audit CAP-13). Now only data older than FOCUS_STALE_MS is refetched on
 * focus. Mounting a page still refetches as before; a query that must refetch
 * on every focus opts in with `refetchOnWindowFocus: "always"`.
 */
export function refetchOnFocusIfStale(query: Pick<Query, "state">): boolean {
  return Date.now() - query.state.dataUpdatedAt > FOCUS_STALE_MS;
}

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        // The default retries every failure three times with backoff, so a bad
        // link sat on "Loading…" for ~7s before saying it was not found. A 4xx
        // will not change on retry.
        retry: shouldRetry,
        refetchOnWindowFocus: refetchOnFocusIfStale,
      },
    },
  });
}
