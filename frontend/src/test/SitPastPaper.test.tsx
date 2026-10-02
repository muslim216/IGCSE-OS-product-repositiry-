import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, test, vi } from "vitest";
import SitPastPaperPage from "../student/SitPastPaperPage";

/* Sitting a past paper: what the page promises once it is marked, and what the
   picker shows once the answers have gone. */

const PAPER = {
  id: 5,
  subject_id: 1,
  title: "Chemistry Paper 2",
  display_title: "Chemistry Paper 2",
  session_label: null,
  paper_number: null,
  total_marks: 80,
  duration_minutes: 90,
  paper_name: "paper.pdf",
  mark_scheme_name: null,
  extraction_error: null,
  question_count: 0,
  questions: [],
};

const MARKED = {
  submission_id: 3,
  past_paper_id: 5,
  title: PAPER.display_title,
  session_label: null,
  paper_number: null,
  subject_name: "Chemistry",
  status: "marked",
  timed: true,
  time_taken_minutes: 85,
  attempted_at: "2026-09-14",
  submitted_at: "2026-09-14T10:00:00Z",
  raw_marks: 61,
  max_marks: 80,
};

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

/** `attempt` is what my-attempt answers, before and after an upload. */
function stubFetch(attempt: unknown) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      // Most specific first — "/past-papers/5" is a prefix of every other path.
      if (url.includes("/my-attempt")) return json(attempt);
      if (url.includes("/attempts") && init?.method === "POST") {
        return json({ ...MARKED, status: "being_marked", raw_marks: null }, 201);
      }
      if (url.includes("/past-papers/5")) return json(PAPER);
      return json(null);
    }),
  );
}

function renderSit() {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter initialEntries={["/student/past-papers/5"]}>
        <Routes>
          <Route path="/student/past-papers/:pastPaperId" element={<SitPastPaperPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

test("a marked paper points to Progress without promising per-question marks there", async () => {
  // Progress shows grades and topics; nothing shows a student a past paper's
  // marks question by question, so the page must not send them looking.
  stubFetch(MARKED);
  renderSit();

  expect(await screen.findByText("Your result")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "progress" })).toHaveAttribute(
    "href",
    "/student/progress",
  );
  expect(screen.queryByText(/per-question|feedback/i)).not.toBeInTheDocument();
});

test("the picker forgets the uploaded files once they have gone", async () => {
  // my-attempt stays empty after the upload, holding the form on screen — the
  // window before the refetch lands, or a refetch that fails.
  stubFetch(null);
  renderSit();

  const input = await screen.findByLabelText("Your answers");
  const answers = new File(["%PDF-1.4"], "answers.pdf", { type: "application/pdf" });
  fireEvent.change(input, { target: { files: [answers] } });
  expect(screen.getByText("answers.pdf")).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "Submit for marking" }));
  await waitFor(() => expect(screen.queryByText("answers.pdf")).not.toBeInTheDocument());
  expect(screen.getByText("Choose photos or a PDF")).toBeInTheDocument();
});
