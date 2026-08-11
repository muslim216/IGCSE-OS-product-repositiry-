import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, test, vi } from "vitest";
import ClassReadinessPage from "../tutor/ClassReadinessPage";

const SUBJECT = { id: 1, exam_board: "CIE", code: "0625", name: "Physics", grade_scale: "9-1" };

function stubFetch(empty = false) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200 });
      if (empty && url.includes("/groups")) return json([]);
      if (url.includes("/analytics/groups/5")) {
        return json({
          weak_students: [
            { student_id: 9, student_name: "Aya Hassan", subject_name: "Physics", score: 42.5 },
            { student_id: 10, student_name: "Omar Ali", subject_name: "Physics", score: 81 },
          ],
          weak_topics: [],
          agreement: { total_marked_questions: 0, ai_agreed: 0, agreement_rate: null },
        });
      }
      if (url.includes("/groups")) {
        return json([{ id: 5, name: "Physics A", subject: SUBJECT, member_count: 2 }]);
      }
      return json([]);
    }),
  );
}

function renderPage() {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter>
        <ClassReadinessPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

test("renders the shared readiness table, coloured by band, not bespoke cards", async () => {
  stubFetch();
  renderPage();

  // The learners arrive through <ReadinessTable>, which carries the status badge.
  expect(await screen.findByText("Aya Hassan")).toBeInTheDocument();
  const ayaRow = (await screen.findByText("Aya Hassan")).closest("tr")!;
  expect(within(ayaRow).getByText("At risk")).toBeInTheDocument();
  expect(within(ayaRow).getByRole("link", { name: /Review evidence/ })).toHaveAttribute(
    "href",
    "/tutor/students/9",
  );

  const omarRow = (await screen.findByText("Omar Ali")).closest("tr")!;
  expect(within(omarRow).getByText("On track")).toBeInTheDocument();
});

test("says a class needs to be created rather than showing an empty table", async () => {
  stubFetch(true);
  renderPage();
  expect(await screen.findByText("You haven't set up a class yet.")).toBeInTheDocument();
});
