/**
 * `applyUser` writes the identity every role gate reads, and its callers are
 * mutation callbacks — code that runs whenever the server answers, which may be
 * after the user has left. The provider's state, not the closure that started
 * the write, decides whether the answer still applies.
 */
import { act, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { AuthProvider, useApplyUser, useAuth } from "../auth/AuthContext";
import type { AuthResponse, User } from "../api/client";

const alice = {
  id: 1,
  email: "alice@example.com",
  username: null,
  role: "student",
  name: "Alice",
} as unknown as User;

let ctx: ReturnType<typeof useAuth>;
// `useApplyUser()` binds the epoch current at whichever render produced it —
// exactly what a `useMutation`'s `onSuccess` closes over in real callers. This
// is captured fresh on every render of Probe, the same way a component's own
// render would.
let boundApplyUser: (user: User) => void;

function Probe() {
  ctx = useAuth();
  boundApplyUser = useApplyUser();
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
  act(() => boundApplyUser({ ...alice, name: "Alice Renamed" }));

  expect(screen.getByTestId("who")).toHaveTextContent("signed out");
  expect(localStorage.getItem("avora-tokens")).toBeNull();
});

test("a late update belonging to a different account is ignored", async () => {
  await mounted();

  act(() => boundApplyUser({ ...alice, id: 2, name: "Bob" }));

  expect(screen.getByTestId("who")).toHaveTextContent("Alice");
});

test("an update for the signed-in user still applies", async () => {
  await mounted();

  act(() => boundApplyUser({ ...alice, name: "Alice Renamed" }));

  expect(screen.getByTestId("who")).toHaveTextContent("Alice Renamed");
});

test("a write from before a sign-out/sign-back-in cycle is ignored even for the same account", async () => {
  await mounted();

  // Captured now, while signed in under the epoch this render started with —
  // the closure a `useMutation`'s `onSuccess` would have bound at this point.
  // TanStack Query keeps calling this exact closure even once the component
  // that created it has unmounted (verified separately), so an id check alone
  // cannot tell this write apart from one the *current* session actually made:
  // both name Alice's id.
  const staleWrite = boundApplyUser;

  act(() => ctx.signOut());
  act(() =>
    ctx.signIn({
      user: alice,
      tokens: { access_token: "t2", token_type: "bearer" },
    } as unknown as AuthResponse),
  );
  await waitFor(() => expect(screen.getByTestId("who")).toHaveTextContent("Alice"));

  act(() => staleWrite({ ...alice, name: "Stale Rename" }));

  expect(screen.getByTestId("who")).toHaveTextContent("Alice");
  expect(screen.getByTestId("who")).not.toHaveTextContent("Stale Rename");
});
