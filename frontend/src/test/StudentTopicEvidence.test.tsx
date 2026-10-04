import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, test, vi } from "vitest";
import StudentDetailPage from "../tutor/StudentDetailPage";

/* The evidence behind one topic on the tutor's student profile. A failed load
   offers its own retry: "refresh the page" would close the panel and lose the
   topic the tutor had opened. */

const SUBJECT = {
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
  topics_with_evidence: 1,
  topic_count: 1,
  homework_assignment_count: null,
  homework_submitted_count: null,
  topics: [
    {
      topic_id: 10,
      topic_code: "1.3",
      topic_title: "Atomic structure",
      score: 40,
      confidence: "high",
      evidence_count: 1,
      tutor_estimate: false,
    },
  ],
  weak_topics: [],
  is_updating: false,
  computed_at: null,
  rationale: null,
  recommended_revision: null,
  verdict: { status: "on_track", reason_topics: [], next_step: "Keep up the current plan." },
};

const EVIDENCE = {
  topic_id: 10,
  topic_code: "1.3",
  topic_title: "Atomic structure",
  score: 40,
  confidence: "high",
  tutor_estimate: false,
  evidence: [
    {
      source_type: "homework",
      label: "HW3 — Atoms",
      score_pct: 40,
      occurred_at: "2026-09-20T10:00:00Z",
    },
  ],
};

const NO_TALLY = { mistakes: 0, severity_total: 0, categories: [] };
/** An unexamined rollup, so the rest of the profile renders and stays quiet. */
const NO_MISTAKES = {
  student_id: 2,
  subject_id: 3,
  analysed_questions: 0,
  total: NO_TALLY,
  topics: [],
  topicless: NO_TALLY,
  chapters: [],
  chapterless: NO_TALLY,
};

afterEach(() => vi.unstubAllGlobals());

test("a topic's evidence that fails to load can be retried in place", async () => {
  let evidenceFails = true;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const path = new URL(String(input), "http://localhost").pathname;
      const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
      if (path.endsWith("/attendance"))
        return json({ lessons: 0, present: 0, absent: 0, not_taken: 0, rate: null, classes: [] });
      if (path === "/api/v1/readiness/students/2")
        return json({ student_id: 2, student_name: "Sara", subjects: [SUBJECT] });
      if (path === "/api/v1/readiness/students/2/topics/10/evidence")
        return evidenceFails ? json({ detail: "boom" }, 500) : json(EVIDENCE);
      if (path === "/api/v1/students/2/mistakes") return json(NO_MISTAKES);
      return json([]);
    }),
  );
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

  fireEvent.click(await screen.findByRole("button", { name: /Atomic structure/ }));
  const retry = await screen.findByRole("button", { name: "Try again" });
  expect(screen.queryByText(/refresh the page/)).not.toBeInTheDocument();

  evidenceFails = false;
  fireEvent.click(retry);
  expect(await screen.findByText("HW3 — Atoms", { exact: false })).toBeInTheDocument();
});
