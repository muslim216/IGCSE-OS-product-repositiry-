/**
 * `applyUser` writes the identity every role gate reads, and its callers are
 * mutation callbacks — code that runs whenever the server answers, which may be
 * after the user has left. The provider's state, not the closure that started
 * the write, decides whether the answer still applies.
 */
import { act, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { AuthProvider, useAuth } from "../auth/AuthContext";
import type { User } from "../api/client";

const alice = {
  id: 1,
  email: "alice@example.com",
  username: null,
  role: "student",
  name: "Alice",
} as unknown as User;

let ctx: ReturnType<typeof useAuth>;

function Probe() {
  ctx = useAuth();
  return <div data-testid="who">{ctx.loading ? "…" : (ctx.user?.name ?? "signed out")}</div>;
}

beforeEach(() => {
  localStorage.setItem("avora-tokens", JSON.stringify({ access_token: "t", token_type: "bearer" }));
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).includes("/auth/me")) {
        return new Response(JSON.stringify(alice), { status: 200 });
      }
      return new Response("{}", { status: 200 });
    }),
  );
});

afterEach(() => {
  localStorage.clear();
  vi.unstubAllGlobals();
});

async function mounted() {
  render(
    <AuthProvider>
      <Probe />
    </AuthProvider>,
  );
  await waitFor(() => expect(screen.getByTestId("who")).toHaveTextContent("Alice"));
}

test("a late identity update after sign-out does not restore the session", async () => {
  await mounted();

  // The order a slow PATCH produces: the user signs out while it is in flight,
  // then it resolves. Without the guard the provider ends up with tokens gone
  // and `user` set — which every role gate reads as signed in.
  act(() => ctx.signOut());
  act(() => ctx.applyUser({ ...alice, name: "Alice Renamed" }));

  expect(screen.getByTestId("who")).toHaveTextContent("signed out");
  expect(localStorage.getItem("avora-tokens")).toBeNull();
});

test("a late update belonging to a different account is ignored", async () => {
  await mounted();

  act(() => ctx.applyUser({ ...alice, id: 2, name: "Bob" }));

  expect(screen.getByTestId("who")).toHaveTextContent("Alice");
});

test("an update for the signed-in user still applies", async () => {
  await mounted();

  act(() => ctx.applyUser({ ...alice, name: "Alice Renamed" }));

  expect(screen.getByTestId("who")).toHaveTextContent("Alice Renamed");
});
