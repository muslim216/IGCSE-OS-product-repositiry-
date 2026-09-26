import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, test, vi } from "vitest";
import StudentDetailPage from "../tutor/StudentDetailPage";

/* Saved observations on the tutor's student profile (PROD-15).

   An observation is a profile note and never readiness evidence, so this list
   is the only place one is ever shown again. A failed load must not read as
   "no observations" (UX-19). */

/** `observations` is what the list endpoint returns, or a status to fail with. */
function stub(observations: unknown, failWith?: number) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), "http://localhost");
      const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200 });
      if (url.pathname === "/api/v1/readiness/students/2") {
        return json({ student_id: 2, student_name: "Sara", subjects: [] });
      }
      if (url.pathname === "/api/v1/students/2/observations") {
        return failWith
          ? new Response(JSON.stringify({ detail: "boom" }), { status: failWith })
          : json(observations);
      }
      return json([]);
    }),
  );
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/tutor/students/2"]}>
        <Routes>
          <Route path="/tutor/students/:studentId" element={<StudentDetailPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

test("a saved observation shows its comment, topic and rating", async () => {
  stub([
    {
      id: 1,
      student_id: 2,
      topic_id: null,
      comment: "Asks sharp questions in class",
      rating: 85,
      created_at: "2026-09-20T10:00:00Z",
    },
  ]);
  renderPage();

  const row = (await screen.findByText("Asks sharp questions in class")).closest("li")!;
  expect(row).toHaveTextContent("General");
  expect(row).toHaveTextContent("Rating 85/100");
});

test("no observations reads as none, not as a failure", async () => {
  stub([]);
  renderPage();
  expect(await screen.findByText("No observations yet.")).toBeInTheDocument();
});

test("a failed load says so rather than claiming there are none", async () => {
  stub(null, 500);
  renderPage();
  expect(await screen.findByText("Could not load observations.")).toBeInTheDocument();
  expect(screen.queryByText("No observations yet.")).not.toBeInTheDocument();
});
