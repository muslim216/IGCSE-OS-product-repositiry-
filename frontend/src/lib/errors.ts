import { ApiError } from "../api/client";

/**
 * The sentence a person sees when something fails.
 *
 * Raw failures never reach the screen: "TypeError: Failed to fetch" and a bare
 * "Internal Server Error" tell a tutor or a fifteen-year-old nothing they can
 * act on, and they read as an unfinished product. A 4xx from the API carries a
 * message written for the user (API-11), so it is passed through; anything
 * else is replaced with what to do next.
 */
export function friendlyError(err: unknown, fallback = "Something went wrong. Try again."): string {
  if (err instanceof ApiError) {
    if (err.status >= 500) {
      return "Something went wrong on our side. Try again in a minute.";
    }
    if (err.status === 404) return "We couldn't find that. It may have been removed.";
    return err.message || fallback;
  }
  if (err instanceof TypeError) {
    return "Can't reach avora right now. Check your connection and try again.";
  }
  return fallback;
}

/** A client error means retrying will give the same answer, so don't. */
export function shouldRetry(failureCount: number, err: unknown): boolean {
  if (err instanceof ApiError && err.status < 500) return false;
  return failureCount < 2;
}
