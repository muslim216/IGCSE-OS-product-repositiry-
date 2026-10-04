import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, test, vi } from "vitest";
import GroupAnalyticsPage from "../tutor/GroupAnalyticsPage";
import type { components } from "../api/schema";

// The generated contract, not the hand-written copy in api/readiness.ts, so a
// fixture missing a field the server sends fails to compile (FE-4).
type TutorAnalytics = components["schemas"]["TutorAnalytics"];

const BASE: TutorAnalytics = {
  weak_students: [],
  weak_topics: [],
  topic_mean_count: 0,
  agreement: { total_marked_questions: 0, ai_agreed: 0, agreement_rate: null },
};

function stubFetch(analytics: TutorAnalytics, overview: unknown = { learners: [] }) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200 });
      if (url.includes("/analytics/groups/")) return json(analytics);
      if (url.includes("/today/classes/")) return json(overview);
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

const WEAK_TOPIC = {
  topic_code: "1.3",
  topic_title: "Atomic structure",
  avg_score: 40,
  student_count: 2,
  includes_tutor_estimate: false,
};
const NO_WEAK_TOPIC = "No topic is at or below the weak threshold.";
const NO_TOPIC_DATA = "Not enough confident topic data yet.";
const SARA = { student_id: 1, student_name: "Sara", subject_name: "Chemistry", score: 88 };
const CONFIDENCE_NOTE = "Class averages count medium- and high-confidence marks only.";
const NO_STUDENT_SCORE =
  "No student has a readiness score yet. Scores appear once their work is marked.";

// Since 5.6 the list holds only topics at or below the tutor's threshold, so an
// empty list with scored learners is a strong class, not a missing measurement
// (PROD-2).
test("a scored class with no weak topic is not reported as having no data", async () => {
  stubFetch({ ...BASE, weak_students: [SARA], topic_mean_count: 4 });
  renderPage();

  expect(await screen.findByText(NO_WEAK_TOPIC)).toBeInTheDocument();
  expect(screen.queryByText("No readiness data yet.")).not.toBeInTheDocument();
  expect(screen.queryByText(NO_TOPIC_DATA)).not.toBeInTheDocument();
  expect(screen.queryByText(CONFIDENCE_NOTE)).not.toBeInTheDocument();
});

// Scored learners but no medium/high-confidence topic mean: nothing was
// compared against the threshold, so "no topic is weak" would be a claim the
// data cannot support (PROD-2).
test("a scored class with no confident topic mean does not claim no topic is weak", async () => {
  stubFetch({ ...BASE, weak_students: [SARA], topic_mean_count: 0 });
  renderPage();

  expect(await screen.findByText(NO_TOPIC_DATA)).toBeInTheDocument();
  expect(screen.queryByText(NO_WEAK_TOPIC)).not.toBeInTheDocument();
  expect(screen.queryByText("No readiness data yet.")).not.toBeInTheDocument();
});

// Topic means can exist while no learner has an overall score; the topics
// panel then reports on the topics, not on the missing overall scores.
test("topic means with no scored learner still report that no topic is weak", async () => {
  stubFetch({ ...BASE, topic_mean_count: 3 });
  renderPage();

  expect(await screen.findByText(NO_WEAK_TOPIC)).toBeInTheDocument();
  // The students panel reports the missing scores; the topics panel does not.
  expect(screen.getByText(NO_STUDENT_SCORE)).toBeInTheDocument();
  expect(screen.queryByText("No readiness data yet.")).not.toBeInTheDocument();
});

test("a class with no scored learners says there is no readiness data yet", async () => {
  stubFetch(BASE);
  renderPage();

  // Each panel says so in its own terms.
  expect(await screen.findByText("No readiness data yet.")).toBeInTheDocument();
  expect(screen.getByText(NO_STUDENT_SCORE)).toBeInTheDocument();
  expect(screen.queryByText(NO_WEAK_TOPIC)).not.toBeInTheDocument();
  expect(screen.queryByText(CONFIDENCE_NOTE)).not.toBeInTheDocument();
});

test("the weak-topic list says which marks the class average counts", async () => {
  stubFetch({ ...BASE, weak_topics: [WEAK_TOPIC] });
  renderPage();

  expect(await screen.findByText(CONFIDENCE_NOTE)).toBeInTheDocument();
});

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
  // The code is still rendered — beside the title, in its own element.
  expect(screen.getByText("1.3")).toBeInTheDocument();
  expect(screen.queryByText("includes tutor estimate")).not.toBeInTheDocument();
});

test("readiness by student reads grade, status and percentage, lowest first", async () => {
  const learner = (id: number, name: string, score: number | null, grade: string | null) => ({
    student_id: id,
    student_name: name,
    score,
    predicted_grade: grade,
    verdict: {
      status: score === null ? "not_enough_data" : "on_track",
      reason_topics: [],
      next_step: "",
    },
  });
  stubFetch(
    { ...BASE, weak_students: [SARA] },
    {
      boundaries_missing: false,
      learners: [
        learner(1, "Sara", 88, "8"),
        learner(2, "Lowe", 41, "3"),
        learner(3, "Unscored", null, null),
      ],
    },
  );
  renderPage();

  const lowe = (await screen.findByText("Lowe")).closest("li")!;
  expect(lowe.textContent).toContain("Grade 3");
  expect(lowe.textContent).toContain("On track");
  expect(lowe.textContent).toContain("41%");
  // A learner without a score is absent, never a 0% row.
  expect(screen.queryByText("Unscored")).not.toBeInTheDocument();
  const names = screen.getAllByRole("link").map((a) => a.textContent);
  expect(names.indexOf("Lowe")).toBeLessThan(names.indexOf("Sara"));
});
