import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, test, vi } from "vitest";
import SubmissionReviewPage from "../tutor/SubmissionReviewPage";
import type { MarkRow } from "../api/homework";

/* The running total on the review page. A question the tutor deliberately left
   blank used to contribute a fabricated 0 to the numerator while still adding
   its max to the denominator, so the tutor was shown a mark the student never
   scored (PROD-2, UX-19). */

function mark(overrides: Partial<MarkRow> & { question_id: number }): MarkRow {
  return {
    number: String(overrides.question_id),
    text_summary: "A question",
    max_marks: 10,
    has_mark_scheme: true,
    ai_transcription: null,
    ai_marks: null,
    ai_feedback: null,
    ai_confidence: null,
    final_marks: null,
    final_feedback: null,
    overridden: false,
    needs_review: false,
    auto_finalized: false,
    remark_requested: false,
    remark_reason: null,
    ...overrides,
  };
}

function stubSubmission(marks: MarkRow[]) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/submissions/1")) {
        return new Response(
          JSON.stringify({
            id: 1,
            assignment_id: 7,
            past_paper_id: null,
            assignment_title: "HW1",
            student_id: 2,
            student_name: "Sara",
            status: "needs_review",
            ai_error: null,
            submitted_at: "2026-06-01T10:00:00Z",
            files: [],
            marks,
          }),
          { status: 200 },
        );
      }
      return new Response(JSON.stringify([]), { status: 200 });
    }),
  );
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/tutor/submissions/1"]}>
        <Routes>
          <Route path="/tutor/submissions/:submissionId" element={<SubmissionReviewPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

test("a blank question is excluded from the total rather than counted as zero", async () => {
  // One question marked 8/10, one left blank. The blank must not drag the
  // total to 8/20 — that is a score the student did not get.
  stubSubmission([
    mark({ question_id: 1, final_marks: 8 }),
    mark({ question_id: 2, final_marks: null }),
  ]);
  renderPage();
  expect(await screen.findByText("8 / 10")).toBeInTheDocument();
  expect(screen.queryByText("8 / 20")).not.toBeInTheDocument();
});

test("the total states how many questions are still unmarked", async () => {
  stubSubmission([
    mark({ question_id: 1, final_marks: 8 }),
    mark({ question_id: 2, final_marks: null }),
    mark({ question_id: 3, final_marks: null }),
  ]);
  renderPage();
  expect(await screen.findByText(/2 not marked yet/)).toBeInTheDocument();
});

test("a fully marked submission shows no unmarked note", async () => {
  stubSubmission([
    mark({ question_id: 1, final_marks: 8 }),
    mark({ question_id: 2, final_marks: 6 }),
  ]);
  renderPage();
  expect(await screen.findByText("14 / 20")).toBeInTheDocument();
  await waitFor(() => expect(screen.queryByText(/not marked yet/)).not.toBeInTheDocument());
});

test("a mark of zero is a real mark and still counts", async () => {
  // The fix must not confuse "the tutor gave 0" with "nobody marked it".
  stubSubmission([
    mark({ question_id: 1, final_marks: 0 }),
    mark({ question_id: 2, final_marks: 5 }),
  ]);
  renderPage();
  expect(await screen.findByText("5 / 20")).toBeInTheDocument();
  await waitFor(() => expect(screen.queryByText(/not marked yet/)).not.toBeInTheDocument());
});
