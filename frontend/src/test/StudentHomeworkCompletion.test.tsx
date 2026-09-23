import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, test, vi } from "vitest";
import StudentDetailPage from "../tutor/StudentDetailPage";

/* Homework completion is a fact shown beside readiness, never blended into
   the score (AV-32, 5.1 task 3): the tutor's student profile must say how
   much was handed in even when that is the only thing there is to say about
   a subject, and must say nothing at all when there is no homework evidence
   to count — a missing count is never shown as 0 (PROD-2). */

function subject(
  homework_assignment_count: number | null,
  homework_submitted_count: number | null,
) {
  return {
    subject_id: 3,
    subject_name: "Chemistry",
    exam_board: "Edexcel IGCSE",
    grade_scale: "9-1",
    score: null,
    predicted_grade: null,
    status: null,
    averaging_score: null,
    averaging_grade: null,
    marked_piece_count: 0,
    direction: null,
    month_delta: null,
    topics_with_evidence: 0,
    topic_count: 0,
    homework_assignment_count,
    homework_submitted_count,
    topics: [],
    weak_topics: [],
    engine: "v2",
    is_updating: false,
    computed_at: null,
    rationale: null,
    recommended_revision: null,
  };
}

/** Answers the whole page; every path but the readiness summary and the
 *  mistake rollup answers empty so the rest of the profile renders without
 *  standing in the way — same convention as StudentMistakeRollup.test.tsx. */
function stub(subjects: ReturnType<typeof subject>[]) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), "http://localhost");
      const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200 });
      if (url.pathname === "/api/v1/readiness/students/2") {
        return json({ student_id: 2, student_name: "Sara", subjects });
      }
      if (url.pathname === "/api/v1/students/2/mistakes") {
        // Nobody examined for mistakes — the mistake section short-circuits
        // on this before touching any other field.
        return json({ analysed_questions: 0 });
      }
      return json([]);
    }),
  );
}

function renderPage() {
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter initialEntries={["/tutor/students/2"]}>
        <Routes>
          <Route path="/tutor/students/:studentId" element={<StudentDetailPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

test("shows the handed-in count beside readiness when both counts are known", async () => {
  stub([subject(5, 4)]);
  renderPage();
  expect(await screen.findByText(/4 of 5 handed in/)).toBeInTheDocument();
});

test("says nothing when there is no homework evidence to count", async () => {
  stub([subject(null, null)]);
  renderPage();
  // Wait for the card itself to have rendered before asserting an absence.
  await screen.findByText("Chemistry");
  expect(screen.queryByText(/handed in/)).not.toBeInTheDocument();
});
