import type { ReactNode } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, test, vi } from "vitest";
import GroupLayout from "../tutor/GroupLayout";

// The class headline has its own tests and its own requests; here it is only
// something the layout renders above the tabs.
vi.mock("../tutor/ClassOverview", () => ({ default: () => null }));

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

/* AppShell keys the page by pathname, so the layout remounts on every tab
   change. The class header holds still across that remount (`avora-still`) and
   arrives normally when the class is first opened — including through the bare
   class URL, which redirects to a tab and so remounts once on the way in. */

function KeyedByPath({ children }: { children: ReactNode }) {
  return <div key={useLocation().pathname}>{children}</div>;
}

function renderClassAt(path: string) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      const body = /\/groups\/1$/.test(url)
        ? {
            id: 1,
            name: "Year 10 Chemistry",
            subject: { id: 1, name: "Chemistry", code: "4CH1", exam_board: "Edexcel IGCSE" },
            member_count: 6,
            awaiting_review_count: 0,
            next_lesson: null,
          }
        : {};
      return new Response(JSON.stringify(body), { status: 200 });
    }),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route
            path="/tutor/groups/:groupId"
            element={
              <KeyedByPath>
                <GroupLayout />
              </KeyedByPath>
            }
          >
            <Route index element={<Navigate to="homework" replace />} />
            <Route path="homework" element={<p>Homework tab</p>} />
            <Route path="students" element={<p>Students tab</p>} />
          </Route>
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

test("opening a class by its bare URL is an arrival, and changing tab is not", async () => {
  renderClassAt("/tutor/groups/1");

  expect(await screen.findByText("Homework tab")).toBeInTheDocument();
  const heading = () => screen.getByRole("heading", { name: "Year 10 Chemistry" });
  expect(heading().closest(".avora-still")).toBeNull();

  fireEvent.click(screen.getByRole("link", { name: "Students" }));

  expect(await screen.findByText("Students tab")).toBeInTheDocument();
  expect(heading().closest(".avora-still")).not.toBeNull();
});
