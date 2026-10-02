import { render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, test, vi } from "vitest";
import SubmitHomeworkPage from "../student/SubmitHomeworkPage";
import type { StudentMarkRow, StudentSubmissionView } from "../api/homework";

/* A student's marked homework, question by question. A remark request contests
   a mark that counted, so it is offered only where there is one: the server
   refuses a request on an unmarked question with a 409, and a button that can
   only ever end in an error is worse than no button. */

function row(over: Partial<StudentMarkRow> = {}): StudentMarkRow {
  return {
    question_id: 1,
    number: "1",
    text_summary: "Balance the equation",
    max_marks: 3,
    final_marks: 2,
    final_feedback: null,
    remark_status: null,
    ...over,
  };
}

function stubFetch(view: StudentSubmissionView) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      const body = url.includes("/my-submission") ? view : [];
      return new Response(JSON.stringify(body), { status: 200 });
    }),
  );
}

function renderPage() {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter initialEntries={["/student/homework/4"]}>
        <Routes>
          <Route path="/student/homework/:assignmentId" element={<SubmitHomeworkPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

test("an unmarked question offers no remark request", async () => {
  stubFetch({
    submission_id: 9,
    status: "marked",
    submitted_at: null,
    finalized_at: null,
    total: 2,
    total_max: 5,
    marks: [
      row({ question_id: 1, number: "1", final_marks: 2 }),
      row({ question_id: 2, number: "2", max_marks: 2, final_marks: null }),
    ],
  });
  renderPage();

  const unmarked = (await screen.findByText("Question 2")).closest("section")!;
  expect(within(unmarked).getByText("Not marked")).toBeInTheDocument();
  expect(within(unmarked).queryByRole("button", { name: "Request a remark" })).toBeNull();

  // The marked question beside it still can be contested.
  const marked = screen.getByText("Question 1").closest("section")!;
  expect(within(marked).getByRole("button", { name: "Request a remark" })).toBeInTheDocument();
});
