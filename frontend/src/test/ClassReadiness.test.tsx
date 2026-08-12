import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, test, vi } from "vitest";
import ClassReadinessPage from "../tutor/ClassReadinessPage";
import type { ClassOverview } from "../api/today";

const SUBJECT = { id: 1, exam_board: "CIE", code: "0625", name: "Physics", grade_scale: "9-1" };

const OVERVIEW: ClassOverview = {
  group_id: 5,
  name: "Physics A",
  subject_name: "Physics",
  score: 61,
  predicted_grade: "6",
  status: "needs_attention",
  boundaries_missing: false,
  member_count: 2,
  students_with_evidence: 2,
  needs_you: [],
  learners: [
    {
      student_id: 9,
      student_name: "Aya Hassan",
      score: 42.5,
      predicted_grade: "3",
      status: "at_risk",
      direction: "down",
    },
    {
      student_id: 10,
      student_name: "Omar Ali",
      score: 81,
      predicted_grade: "8",
      status: "on_track",
      direction: "up",
    },
  ],
  weak_topics: [],
};

function stubFetch(overview: ClassOverview | null = OVERVIEW, groups = true) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200 });
      if (url.includes("/today/classes/") && overview) return json(overview);
      if (url.includes("/groups")) {
        return groups
          ? json([{ id: 5, name: "Physics A", subject: SUBJECT, member_count: 2 }])
          : json([]);
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

test("colours learners by the backend's band, not a percentage threshold", async () => {
  // Aya is 42.5% and Omar 81%. Under the legacy 70/50 cutoffs those would be
  // at_risk and on_track by coincidence — the point is that the badge now comes
  // from the grade's position in its boundary list (UX-28), which is what the
  // class-overview endpoint sends.
  stubFetch();
  renderPage();

  const ayaRow = (await screen.findByText("Aya Hassan")).closest("tr")!;
  expect(within(ayaRow).getByText("At risk")).toBeInTheDocument();
  expect(within(ayaRow).getByRole("link", { name: /Review evidence/ })).toHaveAttribute(
    "href",
    "/tutor/students/9",
  );

  const omarRow = (await screen.findByText("Omar Ali")).closest("tr")!;
  expect(within(omarRow).getByText("On track")).toBeInTheDocument();
});

test("a subject with no boundaries says so instead of colouring against a threshold", async () => {
  stubFetch({
    ...OVERVIEW,
    boundaries_missing: true,
    status: null,
    predicted_grade: null,
    learners: OVERVIEW.learners.map((l) => ({ ...l, status: null, predicted_grade: null })),
  });
  renderPage();

  expect(await screen.findByText("no grade boundaries set")).toBeInTheDocument();
  expect(screen.getByText("Set them →")).toBeInTheDocument();
  // No learner is banded against a cutoff the subject does not have.
  expect(screen.queryByText("At risk")).not.toBeInTheDocument();
  expect(screen.queryByText("On track")).not.toBeInTheDocument();
});

test("says a class needs to be created rather than showing an empty table", async () => {
  stubFetch(null, false);
  renderPage();
  expect(await screen.findByText("You haven't set up a class yet.")).toBeInTheDocument();
});
