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

  await screen.findByText("1.3 Atomic structure");
  expect(screen.queryByText("includes tutor estimate")).not.toBeInTheDocument();
});
