import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Outlet, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, test, vi } from "vitest";
import StudentsTab from "../tutor/tabs/StudentsTab";

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

afterEach(() => vi.unstubAllGlobals());

test("a removed student is listed and the tutor can add them back", async () => {
  let removed = [{ id: 42, name: "Sara", removed_at: "2026-10-20T10:00:00Z" }];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.endsWith("/groups/7/removals")) return json(removed);
    if (url.endsWith("/groups/7/members") && init?.method === "POST") {
      expect(JSON.parse(String(init.body))).toEqual({ student_id: 42 });
      removed = [];
      return new Response(null, { status: 204 });
    }
    if (url.endsWith("/groups/7/invites")) return json([]);
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

  expect(await screen.findByText("Removed from this class")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Add Sara back to this class" }));

  await vi.waitFor(() =>
    expect(screen.queryByText("Removed from this class")).not.toBeInTheDocument(),
  );
  expect(fetchMock.mock.calls.some(([, i]) => i?.method === "POST")).toBe(true);
});
