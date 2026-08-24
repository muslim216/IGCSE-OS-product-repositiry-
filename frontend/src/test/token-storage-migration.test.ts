/**
 * Task 0.6 renamed the localStorage key from `igcse-os-tokens` to
 * `avora-tokens`. A rename with no migration signs out every browser that is
 * currently signed in, and the refresh flow cannot repair it: `api()` only
 * attempts `/auth/refresh` when a stored access token exists, so a null read
 * never reaches the httpOnly refresh cookie that is still valid for another 30
 * days. The user lands on the login page holding a working session.
 *
 * These cover the transition itself, which happens exactly once per browser
 * and is therefore the easiest thing in the change to never test.
 */
import { afterEach, beforeEach, describe, expect, test } from "vitest";
import { getStoredTokens, storeTokens } from "../api/client";

const CURRENT = "avora-tokens";
const LEGACY = "igcse-os-tokens";

beforeEach(() => localStorage.clear());
afterEach(() => localStorage.clear());

describe("the pre-rename key", () => {
  test("a session stored under the old key survives the rename", () => {
    localStorage.setItem(LEGACY, JSON.stringify({ access_token: "abc", token_type: "bearer" }));

    expect(getStoredTokens()).toEqual({ access_token: "abc", token_type: "bearer" });
    // Moved, not copied: the old key must not keep a credential nothing will
    // ever use again.
    expect(localStorage.getItem(LEGACY)).toBeNull();
    expect(JSON.parse(localStorage.getItem(CURRENT)!)).toEqual({
      access_token: "abc",
      token_type: "bearer",
    });
  });

  test("the current key wins and the old one is cleared with it", () => {
    localStorage.setItem(CURRENT, JSON.stringify({ access_token: "new", token_type: "bearer" }));
    localStorage.setItem(LEGACY, JSON.stringify({ access_token: "old", token_type: "bearer" }));

    expect(getStoredTokens()?.access_token).toBe("new");
    // Leaving it would survive sign-out — storeTokens(null) clears only the
    // current key, so the next read would migrate the stale token back and the
    // app would look signed in again until a request failed.
    expect(localStorage.getItem(LEGACY)).toBeNull();
  });

  test("signing out with both keys present does not resurrect the old session", () => {
    localStorage.setItem(CURRENT, JSON.stringify({ access_token: "new", token_type: "bearer" }));
    localStorage.setItem(LEGACY, JSON.stringify({ access_token: "old", token_type: "bearer" }));

    getStoredTokens();
    storeTokens(null);

    expect(getStoredTokens()).toBeNull();
  });

  test("an unusable current value does not cost a valid pre-rename session", () => {
    // The migration exists to keep a signed-in browser signed in. A current
    // entry that cannot be read is not a session — treating its mere presence
    // as one throws away the only real credential the browser holds, and the
    // refresh cookie cannot repair it (see the header comment).
    localStorage.setItem(CURRENT, "{not json");
    localStorage.setItem(LEGACY, JSON.stringify({ access_token: "old", token_type: "bearer" }));

    expect(getStoredTokens()?.access_token).toBe("old");
    expect(localStorage.getItem(LEGACY)).toBeNull();
    expect(JSON.parse(localStorage.getItem(CURRENT)!).access_token).toBe("old");
  });

  test("a current value with no access token is treated the same way", () => {
    localStorage.setItem(CURRENT, JSON.stringify({ token_type: "bearer" }));
    localStorage.setItem(LEGACY, JSON.stringify({ access_token: "old", token_type: "bearer" }));

    expect(getStoredTokens()?.access_token).toBe("old");
  });

  test("both keys unusable leaves nothing behind", () => {
    localStorage.setItem(CURRENT, "{not json");
    localStorage.setItem(LEGACY, "{also not json");

    expect(getStoredTokens()).toBeNull();
    expect(localStorage.getItem(CURRENT)).toBeNull();
    expect(localStorage.getItem(LEGACY)).toBeNull();
  });

  test("a current value that parses to a primitive is discarded rather than thrown", () => {
    // JSON.parse succeeds on the literal "null" — it is not malformed JSON,
    // so the try/catch around JSON.parse never fires. Only a follow-up check
    // that the parsed value is actually an object stops `.access_token` from
    // being read off `null`, which would throw uncaught on every request.
    localStorage.setItem(CURRENT, "null");
    localStorage.setItem(LEGACY, JSON.stringify({ access_token: "old", token_type: "bearer" }));

    expect(() => getStoredTokens()).not.toThrow();
    expect(getStoredTokens()?.access_token).toBe("old");
  });

  test("an unparseable old value is discarded rather than thrown", () => {
    // Every request reads this. Throwing here would take down the app
    // including the login that would replace the bad entry.
    localStorage.setItem(LEGACY, "{not json");

    expect(getStoredTokens()).toBeNull();
    expect(localStorage.getItem(LEGACY)).toBeNull();
    expect(localStorage.getItem(CURRENT)).toBeNull();
  });

  test("signing out clears the session and nothing resurrects it", () => {
    localStorage.setItem(LEGACY, JSON.stringify({ access_token: "abc", token_type: "bearer" }));
    getStoredTokens();
    storeTokens(null);

    expect(getStoredTokens()).toBeNull();
  });
});
