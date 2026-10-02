import { render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, test, vi } from "vitest";
import AssignmentDetailPage from "../tutor/AssignmentDetailPage";

/* The tutor's homework page. A bad link must end in a "not found" page rather
   than a spinner, and the question table speaks the tutor's language: topic
   names rather than syllabus codes, "Mark scheme" rather than "MS?". */

const TOPIC = { id: 11, code: "1.3", title: "Atomic structure", parent_id: null, weight: 1 };

const ASSIGNMENT = {
  id: 4,
  group_id: 5,
  classified_id: null,
  title: "HW3",
  instructions: null,
  due_at: null,
  question_range: null,
  status: "published",
  extraction_error: null,
  questions: [
    {
      id: 1,
      number: "1",
      text_summary: "Define an isotope",
      max_marks: 2,
      has_mark_scheme: true,
      topics: [TOPIC],
    },
  ],
};

function stub(assignment: unknown, status = 200) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), "http://localhost");
      const json = (body: unknown, code = 200) =>
        new Response(JSON.stringify(body), { status: code });
      if (url.pathname === "/api/v1/assignments/4") return json(assignment, status);
      if (url.pathname === "/api/v1/groups/5") {
        return json({
          id: 5,
          name: "Chem",
          subject: {
            id: 3,
            exam_board: "CIE",
            code: "0620",
            name: "Chemistry",
            grade_scale: "9-1",
          },
          members: [],
          member_count: 0,
          students_with_evidence: 0,
          published_assignment_count: 1,
          awaiting_review_count: 0,
          next_lesson: null,
        });
      }
      if (url.pathname === "/api/v1/subjects/3/topics") return json([TOPIC]);
      if (url.pathname === "/api/v1/assignments/4/submissions") {
        return json([
          {
            id: 9,
            student_id: 2,
            student_name: "Sara",
            status: "finalized",
            submitted_at: "2026-09-01T10:00:00Z",
            total_final: 8,
            total_max: 10,
          },
        ]);
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
      <MemoryRouter initialEntries={["/tutor/assignments/4"]}>
        <Routes>
          <Route path="/tutor/assignments/:assignmentId" element={<AssignmentDetailPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

test("a link to homework that does not exist says so, with a way back", async () => {
  stub({ detail: "Assignment not found" }, 404);
  renderPage();
  expect(
    await screen.findByRole("heading", { name: "We couldn't find that homework" }),
  ).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /All classes/ })).toHaveAttribute(
    "href",
    "/tutor/classes",
  );
});

test("questions show topic names and a plainly named mark-scheme column", async () => {
  stub(ASSIGNMENT);
  renderPage();
  const table = await screen.findByRole("table");
  expect(within(table).getByRole("columnheader", { name: "Mark scheme" })).toBeInTheDocument();
  expect(await within(table).findByText("Atomic structure")).toBeInTheDocument();
  expect(within(table).queryByText("1.3")).not.toBeInTheDocument();
});

test("a marked submission reads as a score with a link to the work", async () => {
  stub(ASSIGNMENT);
  renderPage();
  expect(await screen.findByText("8/10")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "View Sara's work" })).toHaveAttribute(
    "href",
    "/tutor/submissions/9",
  );
});
