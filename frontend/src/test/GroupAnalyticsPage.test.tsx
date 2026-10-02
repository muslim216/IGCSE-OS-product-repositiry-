import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, test, vi } from "vitest";
import GroupAnalyticsPage from "../tutor/GroupAnalyticsPage";
import type { TutorAnalytics } from "../api/readiness";

const BASE: TutorAnalytics = {
  weak_students: [],
  weak_topics: [],
  agreement: { total_marked_questions: 0, ai_agreed: 0, agreement_rate: null },
};

function stubFetch(analytics: TutorAnalytics) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200 });
      if (url.includes("/analytics/groups/")) return json(analytics);
      return json([]);
    }),
  );
}

function renderPage() {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter initialEntries={["/tutor/groups/5/analytics"]}>
        <Routes>
          <Route path="/tutor/groups/:groupId/analytics" element={<GroupAnalyticsPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

test("a weakest topic that leans on a tutor estimate is labelled", async () => {
  stubFetch({
    ...BASE,
    weak_topics: [
      {
        topic_code: "1.3",
        topic_title: "Atomic structure",
        avg_score: 40,
        student_count: 2,
        includes_tutor_estimate: true,
      },
    ],
  });
  renderPage();

  expect(await screen.findByText("includes tutor estimate")).toBeInTheDocument();
});

test("a weakest topic from marked work alone carries no estimate label", async () => {
  stubFetch({
    ...BASE,
    weak_topics: [
      {
        topic_code: "1.3",
        topic_title: "Atomic structure",
        avg_score: 40,
        student_count: 2,
        includes_tutor_estimate: false,
      },
    ],
  });
  renderPage();

  await screen.findByText("Atomic structure");
  expect(screen.queryByText("includes tutor estimate")).not.toBeInTheDocument();
});

test("no weak topic beside scored students is not reported as 'no readiness data'", async () => {
  // Students can carry readiness while no topic's class average is at or below
  // the weak threshold — the topic list is empty for a different reason, and
  // saying "no readiness data" beside 58% and 62% contradicted the page.
  stubFetch({
    ...BASE,
    weak_students: [
      { student_id: 1, student_name: "Sara", subject_name: "Chemistry", score: 58 },
      { student_id: 2, student_name: "Omar", subject_name: "Chemistry", score: 62 },
    ],
  });
  renderPage();

  expect(await screen.findByText("No topic stands out as weak right now.")).toBeInTheDocument();
  expect(screen.queryByText(/No readiness data/)).not.toBeInTheDocument();
});
