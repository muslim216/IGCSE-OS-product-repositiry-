import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Outlet, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, test, vi } from "vitest";
import StudentsTab from "../tutor/tabs/StudentsTab";

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

afterEach(() => vi.unstubAllGlobals());

test("a tutor switches the class link off after confirming, then sees no active link", async () => {
  let live = [{ code: "abc123", kind: "student_join", expires_at: null }];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    if (String(input).endsWith("/groups/7/invites")) {
      if (init?.method === "DELETE") {
        live = [];
        return new Response(null, { status: 204 });
      }
      return json(live);
    }
    return json(null);
  });
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

  const revoked = () => fetchMock.mock.calls.some(([, i]) => i?.method === "DELETE");
  fireEvent.click(await screen.findByRole("button", { name: "Switch off link" }));
  // Nothing is revoked until the dialog is confirmed.
  expect(revoked()).toBe(false);
  const buttons = await screen.findAllByRole("button", { name: "Switch off link" });
  fireEvent.click(buttons[buttons.length - 1]);

  expect(await screen.findByText("No active link")).toBeInTheDocument();
  await waitFor(() => expect(revoked()).toBe(true));
  expect(screen.getByRole("button", { name: /Make a new link/ })).toBeInTheDocument();
});
