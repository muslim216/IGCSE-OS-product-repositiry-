import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, test, vi } from "vitest";
import StudentDetailPage from "../tutor/StudentDetailPage";
import { axeViolations } from "./axe";

afterEach(() => vi.unstubAllGlobals());

const subject = {
  subject_id: 5,
  subject_name: "Chemistry",
  exam_board: "CIE",
  grade_scale: "9-1",
  score: 60,
  predicted_grade: "5",
  status: "on_track",
  verdict: { status: "needs_attention", reason_topics: [], next_step: "n" },
  averaging_score: null,
  averaging_grade: null,
  marked_piece_count: 3,
  direction: "up",
  month_delta: null,
  topics_with_evidence: 1,
  topic_count: 2,
  homework_assignment_count: null,
  is_updating: false,
  calculation_failed: false,
  topics: [],
  weak_topics: [],
};

// Real content in every tab, so axe sees the cards and forms and not only the
// skeletons they show while loading.
const CONTENT: Record<string, RegExp> = {
  progress: /Mistakes in Chemistry/,
  work: /^Reports$/,
  notes: /Starting estimate/,
  about: /Linked parents/,
};

test.each(Object.keys(CONTENT))("the %s tab has no axe violations", async (t) => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), "http://localhost");
      let body: unknown = [];
      if (url.pathname === "/api/v1/readiness/students/2")
        body = { student_id: 2, student_name: "Sara", subjects: [subject] };
      else if (url.pathname.includes("/mistakes")) body = { analysed_questions: 0 };
      else if (url.pathname.endsWith("/erasure")) body = null;
      return new Response(JSON.stringify(body), { status: 200 });
    }),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const { container } = render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[`/tutor/students/2?tab=${t}`]}>
        <Routes>
          <Route path="/tutor/students/:studentId" element={<StudentDetailPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  await screen.findByRole("tab", { name: "Progress" });
  await screen.findByRole("tabpanel");
  expect((await screen.findAllByText(CONTENT[t], {}, { timeout: 2000 })).length).toBeGreaterThan(0);
  expect(await axeViolations(container)).toEqual([]);
});
