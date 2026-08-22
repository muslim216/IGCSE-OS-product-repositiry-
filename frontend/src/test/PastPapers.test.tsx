import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import StudentPastPapersPage from "../student/PastPapersPage";
import TutorPastPapersPage from "../tutor/PastPapersPage";

const paper = {
  id: 1,
  subject_id: 1,
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
  localStorage.setItem(
    "igcse-os-tokens",
    JSON.stringify({ access_token: "t", token_type: "bearer" }),
  );
});

afterEach(() => {
  localStorage.clear();
  vi.unstubAllGlobals();
});

test("a student sees the papers they can sit", async () => {
  mockFetch([paper]);
  renderPage(<StudentPastPapersPage />);
  expect(await screen.findByText(/November 2026/)).toBeInTheDocument();
  expect(screen.getByText(/80 marks/)).toBeInTheDocument();
});

test("a student with no papers is told so rather than shown an empty page", async () => {
  mockFetch([]);
  renderPage(<StudentPastPapersPage />);
  expect(await screen.findByText(/No past papers have been added/)).toBeInTheDocument();
});

test("the tutor upload form requires the mark scheme before it will submit", async () => {
  mockFetch([paper]);
  renderPage(<TutorPastPapersPage />);
  const button = await screen.findByRole("button", { name: /Add past paper/ });
  expect(button).toBeDisabled();
  expect(screen.getByText(/mark scheme is required/)).toBeInTheDocument();
});

test("the tutor list shows extraction still in progress", async () => {
  mockFetch([{ ...paper, question_count: 0 }]);
  renderPage(<TutorPastPapersPage />);
  expect(await screen.findByText(/Reading the questions out of the paper/)).toBeInTheDocument();
});
