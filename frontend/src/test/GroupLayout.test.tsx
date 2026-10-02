import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, test, vi } from "vitest";
import GroupLayout from "../tutor/GroupLayout";

/* A class URL that cannot name a class is a wrong link, not a failed load:
   "didn't load — try again" offers a retry that can never succeed. */

function renderAt(path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/tutor/groups/:groupId" element={<GroupLayout />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

test("a class id that is not a whole number is not found, and is never asked for", async () => {
  const fetch = vi.fn(async () => new Response(JSON.stringify({ detail: "x" }), { status: 422 }));
  vi.stubGlobal("fetch", fetch);
  renderAt("/tutor/groups/chemistry");

  expect(await screen.findByText("We couldn't find that class")).toBeInTheDocument();
  expect(screen.queryByText("This class didn't load")).not.toBeInTheDocument();
  expect(fetch).not.toHaveBeenCalled();
});

test("a class the API does not know is not found", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify({ detail: "Group not found" }), { status: 404 })),
  );
  renderAt("/tutor/groups/999");

  expect(await screen.findByText("We couldn't find that class")).toBeInTheDocument();
});
