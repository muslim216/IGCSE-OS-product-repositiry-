import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Outlet, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, test, vi } from "vitest";
import StudentsTab from "../tutor/tabs/StudentsTab";

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

afterEach(() => vi.unstubAllGlobals());

/** The students tab for class 7, with `fetch` answered by `respond`. */
function renderTab(respond: (url: string, init?: RequestInit) => Response) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) =>
    respond(String(input), init),
  );
  vi.stubGlobal("fetch", fetchMock);
  const group = { id: 7, name: "Y10", members: [], subject: { name: "Chemistry" } };
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter>
        <Routes>
          <Route element={<Outlet context={{ group, groupId: 7 }} />}>
            <Route index element={<StudentsTab />} />
          </Route>
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return (method: string) => fetchMock.mock.calls.some(([, i]) => i?.method === method);
}

test("a tutor switches the class link off after confirming, then sees no active link", async () => {
  let live = [{ code: "abc123", kind: "student_join", expires_at: null }];
  const called = renderTab((url, init) => {
    if (!url.endsWith("/groups/7/invites")) return json([]);
    if (init?.method !== "DELETE") return json(live);
    live = [];
    return new Response(null, { status: 204 });
  });

  fireEvent.click(await screen.findByRole("button", { name: "Switch off link" }));
  // Nothing is revoked until the dialog is confirmed.
  expect(called("DELETE")).toBe(false);
  const buttons = await screen.findAllByRole("button", { name: "Switch off link" });
  fireEvent.click(buttons[buttons.length - 1]);

  expect(await screen.findByText("No active link")).toBeInTheDocument();
  await waitFor(() => expect(called("DELETE")).toBe(true));
  expect(screen.getByRole("button", { name: /Make a new link/ })).toBeInTheDocument();
});

test("a removed student is listed and the tutor can add them back", async () => {
  let removed = [{ id: 42, name: "Sara", removed_at: "2026-10-20T10:00:00Z" }];
  const called = renderTab((url, init) => {
    if (url.endsWith("/groups/7/removals")) return json(removed);
    if (url.endsWith("/groups/7/members") && init?.method === "POST") {
      expect(JSON.parse(String(init.body))).toEqual({ student_id: 42 });
      removed = [];
      return new Response(null, { status: 204 });
    }
    return json([]);
  });

  expect(await screen.findByText("Removed from this class")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Add Sara back to this class" }));

  await waitFor(() =>
    expect(screen.queryByText("Removed from this class")).not.toBeInTheDocument(),
  );
  expect(called("POST")).toBe(true);
});
