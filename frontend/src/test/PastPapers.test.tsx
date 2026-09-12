import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import StudentPastPapersPage from "../student/PastPapersPage";
import TutorPastPapersPage from "../tutor/PastPapersPage";

const paper = {
  id: 1,
  subject_id: 1,
  // Deliberately NOT a substring of session_label/paper_number: with the old
  // "November 2026 · Paper 1" the student assertion below passed whether the
  // page rendered `title` or the pair it replaced, so it pinned nothing.
  title: "Cambridge IGCSE Chemistry 0620/21 Paper 2 Multiple Choice",
  display_title: "Cambridge IGCSE Chemistry 0620/21 Paper 2 Multiple Choice",
  session_label: "November 2026",
  paper_number: "Paper 1",
  total_marks: 80,
  duration_minutes: 90,
  booklet_name: "paper.pdf",
  mark_scheme_name: null,
  extraction_error: null,
  question_count: 12,
};

function mockFetch(papers: unknown[]) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/past-papers")) {
        return new Response(JSON.stringify(papers), { status: 200 });
      }
      return new Response(JSON.stringify([]), { status: 200 });
    }),
  );
}

function renderPage(node: React.ReactNode) {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>{node}</MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  localStorage.setItem("avora-tokens", JSON.stringify({ access_token: "t", token_type: "bearer" }));
});

afterEach(() => {
  localStorage.clear();
  vi.unstubAllGlobals();
});

test("a student sees the papers they can sit", async () => {
  mockFetch([paper]);
  renderPage(<StudentPastPapersPage />);
  expect(
    await screen.findByText("Cambridge IGCSE Chemistry 0620/21 Paper 2 Multiple Choice"),
  ).toBeInTheDocument();
  expect(screen.getByText(/80 marks/)).toBeInTheDocument();
});

test("a student with no papers is told so rather than shown an empty page", async () => {
  mockFetch([]);
  renderPage(<StudentPastPapersPage />);
  expect(await screen.findByText(/No past papers have been added/)).toBeInTheDocument();
});

test("the tutor upload form has nothing to type but the subject and files", async () => {
  mockFetch([paper]);
  renderPage(<TutorPastPapersPage />);
  const button = await screen.findByRole("button", { name: /Add past paper/ });
  expect(button).toBeDisabled();
  expect(screen.getByText(/mark scheme is required/)).toBeInTheDocument();
  expect(screen.queryByPlaceholderText(/Session/)).not.toBeInTheDocument();
  expect(screen.queryByPlaceholderText(/Paper, e.g./)).not.toBeInTheDocument();
});

test("the tutor list shows extraction still in progress under an untitled paper", async () => {
  mockFetch([{ ...paper, title: null, display_title: "Untitled paper", question_count: 0 }]);
  renderPage(<TutorPastPapersPage />);
  expect(await screen.findByText("Untitled paper")).toBeInTheDocument();
  expect(screen.getByText(/Reading the questions out of the paper/)).toBeInTheDocument();
});

test("a paper whose extraction failed is never also described as still reading", async () => {
  // The AI reads the name and the questions in one pass, so a failure leaves
  // the paper untitled AND with no questions — the same two signals the
  // in-progress state has. Showing both messages told a tutor it was still
  // working when it had already stopped, indefinitely.
  mockFetch([
    {
      ...paper,
      title: null,
      display_title: "Untitled paper",
      question_count: 0,
      extraction_error: "The upload was not a readable paper",
    },
  ]);
  renderPage(<TutorPastPapersPage />);
  expect(await screen.findByText(/Couldn't read this paper/)).toBeInTheDocument();
  expect(screen.queryByText(/Reading the questions out of the paper/)).not.toBeInTheDocument();
});
