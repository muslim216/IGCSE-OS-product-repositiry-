import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, test, vi } from "vitest";
import SubmissionReviewPage from "../tutor/SubmissionReviewPage";

/* "Try marking again" on work the AI couldn't mark. Before it, a failed
   marking had one way out: the tutor marking every question by hand. */

function body(status: string, aiError: string | null) {
  return {
    id: 1,
    assignment_id: 7,
    past_paper_id: null,
    mock_id: null,
    assignment_title: "HW1",
    student_id: 2,
    student_name: "Sara",
    status,
    ai_error: aiError,
    submitted_at: "2026-06-01T10:00:00Z",
    files: [],
    typed_answer: null,
    subject_id: 3,
    marks: [],
    bare_question_count: 0,
    mistakes_analysed: true,
    can_redo: false,
  };
}

const posts: string[] = [];

function stub(retryAnswer: { status: number; body: unknown }) {
  posts.length = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = new URL(String(input), "http://localhost").pathname;
      const method = (init?.method ?? "GET").toUpperCase();
      const json = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status });
      if (method === "GET" && path === "/api/v1/submissions/1")
        return json(body("ai_failed", "AI is not configured"));
      if (method === "GET" && path === "/api/v1/submissions/review-queue") return json([]);
      if (method === "GET" && /^\/api\/v1\/subjects\/\d+\/mistake-categories$/.test(path))
        return json({ subject_id: 3, subject_name: "Chemistry", source: "none", categories: [] });
      if (method === "POST" && path === "/api/v1/submissions/1/retry-marking") {
        posts.push(path);
        return json(retryAnswer.body, retryAnswer.status);
      }
      return json({ detail: `unstubbed ${method} ${path}` }, 404);
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

test("work the AI couldn't mark can be sent back to it", async () => {
  stub({ status: 200, body: body("submitted", null) });
  renderPage();

  fireEvent.click(await screen.findByRole("button", { name: "Try marking again" }));

  expect(await screen.findByRole("status")).toHaveTextContent("Sent back to the AI");
  expect(posts).toEqual(["/api/v1/submissions/1/retry-marking"]);
  // The failure panel goes with the error: the work is queued again.
  expect(screen.queryByText("The AI couldn't mark this work.")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Try marking again" })).not.toBeInTheDocument();
});

test("a refusal is shown in the server's words and nothing pretends it worked", async () => {
  stub({
    status: 409,
    body: { detail: "The AI is marking this right now. Check back in a few minutes." },
  });
  renderPage();

  fireEvent.click(await screen.findByRole("button", { name: "Try marking again" }));

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "The AI is marking this right now. Check back in a few minutes.",
  );
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
  await waitFor(() => expect(posts).toHaveLength(1));
});
