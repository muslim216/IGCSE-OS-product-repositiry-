import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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

function submissionBody(marks: MarkRow[], id = 1, status = "needs_review") {
  return {
    id,
    assignment_id: 7,
    past_paper_id: null,
    assignment_title: "HW1",
    student_id: 2,
    student_name: "Sara",
    status,
    ai_error: null,
    submitted_at: "2026-06-01T10:00:00Z",
    files: [],
    marks,
  };
}

function queueItem(submission_id: number) {
  return {
    submission_id,
    assignment_id: 7,
    past_paper_id: null,
    assignment_title: "HW1",
    student_id: submission_id,
    student_name: `Student ${submission_id}`,
    submitted_at: "2026-06-01T10:00:00Z",
    unsure_count: 1,
    remark_request_count: 0,
  };
}

/** The real endpoints, matched exactly and by method.
 *
 * A stub that answers `200` to anything containing `/submissions/<id>` cannot
 * fail: a finalize sent as the wrong verb, or to a path that does not exist,
 * still gets a submission body back and the test passes on a request the API
 * would have rejected. Each route below is pinned to its own path and method,
 * and anything else 404s so it surfaces as a failure rather than as silence.
 *
 * The id is a capture, not a constant — a traversal test has to be able to land
 * on the next submission and see it, or it can only assert a button label.
 */
function stubSubmission(marks: MarkRow[], queue: number[] = [], status = "needs_review") {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = new URL(String(input), "http://localhost").pathname;
      const method = (init?.method ?? "GET").toUpperCase();
      const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200 });
      const route = (pattern: RegExp, verb: string) =>
        method === verb ? pattern.exec(path) : null;

      if (route(/^\/api\/v1\/submissions\/review-queue$/, "GET")) return json(queue.map(queueItem));

      const detail = route(/^\/api\/v1\/submissions\/(\d+)$/, "GET");
      if (detail) return json(submissionBody(marks, Number(detail[1]), status));

      const saved = route(/^\/api\/v1\/submissions\/(\d+)\/marks$/, "PUT");
      if (saved) return json(submissionBody(marks, Number(saved[1]), status));

      const finalized = route(/^\/api\/v1\/submissions\/(\d+)\/finalize$/, "POST");
      if (finalized) return json(submissionBody(marks, Number(finalized[1]), "finalized"));

      if (route(/^\/api\/v1\/submissions\/\d+\/marks\/\d+\/history$/, "GET")) return json([]);

      return new Response(JSON.stringify({ detail: `unstubbed ${method} ${path}` }), {
        status: 404,
      });
    }),
  );
}

function renderPage(entry = "/tutor/submissions/1") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[entry]}>
        <Routes>
          <Route path="/tutor/submissions/:submissionId" element={<SubmissionReviewPage />} />
          <Route path="/tutor/review" element={<p>Review queue page</p>} />
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

/* Queue traversal (PR 20). Six submissions used to cost six round trips back out
   through the parent assignment to find the next one. */

test("in a queue the page says which item this is", async () => {
  stubSubmission([mark({ question_id: 1, final_marks: 8 })], [1, 2, 3]);
  renderPage("/tutor/submissions/1?queue=review");
  expect(await screen.findByText("Reviewing 1 of 3")).toBeInTheDocument();
  expect(screen.getByText("← Review queue")).toBeInTheDocument();
});

test("the queue controls are absent when the tutor did not arrive from the queue", async () => {
  stubSubmission([mark({ question_id: 1, final_marks: 8 })], [1, 2, 3]);
  renderPage("/tutor/submissions/1");
  await screen.findByText("8 / 10");
  expect(screen.queryByText(/Reviewing 1 of/)).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Skip" })).not.toBeInTheDocument();
  // The old breadcrumb still returns to the assignment.
  expect(screen.getByText("← HW1")).toBeInTheDocument();
});

test("Skip moves on without writing anything", async () => {
  const fetchMock = vi.fn();
  stubSubmission([mark({ question_id: 1, final_marks: 8 })], [1, 2]);
  const original = globalThis.fetch as typeof fetch;
  vi.stubGlobal("fetch", (...args: Parameters<typeof fetch>) => {
    fetchMock(String(args[0]), args[1]);
    return original(...args);
  });

  renderPage("/tutor/submissions/1?queue=review");
  fireEvent.click(await screen.findByRole("button", { name: "Skip" }));

  // Skip actually advances. Asserting only that nothing was written would pass
  // against a button that does nothing at all.
  expect(await screen.findByText("Reviewing 2 of 2")).toBeInTheDocument();

  // And it moved on without deciding anything — Skip is "not now".
  const wrote = fetchMock.mock.calls.some(
    ([, init]) => init && init.method && init.method !== "GET",
  );
  expect(wrote).toBe(false);
});

test("the last item finalizes to a terminal state, not a blank page", async () => {
  stubSubmission([mark({ question_id: 1, final_marks: 8 })], [1]);
  renderPage("/tutor/submissions/1?queue=review");
  // Last in the queue: the button says so rather than promising a next item.
  fireEvent.click(await screen.findByRole("button", { name: "Finalize & finish" }));
  // The end of the queue lands on the queue itself, never on an empty page.
  expect(await screen.findByText("Review queue page")).toBeInTheDocument();
});

test("a mid-queue item offers Finalize & next and advances to it", async () => {
  stubSubmission([mark({ question_id: 1, final_marks: 8 })], [1, 2]);
  renderPage("/tutor/submissions/1?queue=review");
  fireEvent.click(await screen.findByRole("button", { name: "Finalize & next" }));
  expect(await screen.findByText("Reviewing 2 of 2")).toBeInTheDocument();
});

test("an already-finalized item still lets the tutor move on", async () => {
  stubSubmission([mark({ question_id: 1, final_marks: 8 })], [1, 2], "finalized");
  renderPage("/tutor/submissions/1?queue=review");
  fireEvent.click(await screen.findByRole("button", { name: "Next →" }));
  expect(await screen.findByText("Reviewing 2 of 2")).toBeInTheDocument();
});
