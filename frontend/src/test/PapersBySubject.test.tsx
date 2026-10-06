import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import TutorMocksPage from "../tutor/MocksPage";
import TutorPastPapersPage from "../tutor/PastPapersPage";
import StudentMocksPage from "../student/MocksPage";

const chem = { id: 1, name: "Chemistry", exam_board: "Cambridge", code: "0620" };
const bio = { id: 2, name: "Biology", exam_board: "Edexcel", code: "4BI1" };

const assessment = (id: number, subject_id: number, title: string) => ({
  id,
  subject_id,
  title,
  type: "mock",
  date: "2026-05-01",
  score_count: 3,
});

const paper = (id: number, subject_id: number, display_title: string) => ({
  id,
  subject_id,
  title: display_title,
  display_title,
  session_label: null,
  paper_number: null,
  total_marks: 80,
  duration_minutes: 90,
  paper_name: "paper.pdf",
  mark_scheme_name: null,
  extraction_error: null,
  question_count: 5,
});

function mockApi(data: { subjects: unknown[]; assessments?: unknown[]; papers?: unknown[] }) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      const body = url.includes("/assessments")
        ? (data.assessments ?? [])
        : url.includes("/past-papers")
          ? (data.papers ?? [])
          : url.includes("/subjects")
            ? data.subjects
            : url.includes("/mocks")
              ? (data.assessments ?? [])
              : [];
      return new Response(JSON.stringify(body), { status: 200 });
    }),
  );
}

function Where() {
  const { search } = useLocation();
  return <output data-testid="search">{search}</output>;
}

function renderAt(node: React.ReactNode, entry = "/") {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter initialEntries={[entry]}>
        {node}
        <Where />
      </MemoryRouter>
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

const twoSubjectMocks = {
  subjects: [chem, bio],
  assessments: [
    assessment(1, 1, "Chem mock A"),
    assessment(2, 2, "Bio mock A"),
    assessment(3, 1, "Chem mock B"),
  ],
};

test("tutor mocks: two subjects render two headings with their own items, alphabetically", async () => {
  mockApi(twoSubjectMocks);
  renderAt(<TutorMocksPage />);
  const bioHeading = await screen.findByRole("heading", { name: "Biology" });
  const chemHeading = screen.getByRole("heading", { name: "Chemistry" });
  expect(bioHeading.compareDocumentPosition(chemHeading)).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
  const bioSection = within(screen.getByRole("region", { name: "Biology" }));
  expect(bioSection.getByText("Bio mock A")).toBeInTheDocument();
  expect(bioSection.queryByText("Chem mock A")).toBeNull();
  const chemItems = within(screen.getByRole("region", { name: "Chemistry" })).getAllByRole(
    "listitem",
  );
  expect(chemItems.map((li) => li.textContent)).toEqual([
    expect.stringContaining("Chem mock A"),
    expect.stringContaining("Chem mock B"),
  ]);
});

test("tutor mocks: picking a subject narrows the list and writes ?subject=", async () => {
  mockApi(twoSubjectMocks);
  renderAt(<TutorMocksPage />);
  await screen.findByRole("heading", { name: "Chemistry" });
  fireEvent.change(screen.getByLabelText("Subject"), { target: { value: "2" } });
  expect(screen.getByTestId("search")).toHaveTextContent("?subject=2");
  expect(screen.queryByRole("heading", { name: "Chemistry" })).toBeNull();
  expect(screen.getByRole("heading", { name: "Biology" })).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Subject"), { target: { value: "" } });
  expect(screen.getByTestId("search")).toHaveTextContent(/^$/);
  expect(screen.getByRole("heading", { name: "Chemistry" })).toBeInTheDocument();
});

test("tutor mocks: a stale ?subject= falls back to all subjects", async () => {
  mockApi(twoSubjectMocks);
  renderAt(<TutorMocksPage />, "/?subject=999");
  expect(await screen.findByRole("heading", { name: "Chemistry" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Biology" })).toBeInTheDocument();
  expect(screen.getByLabelText("Subject")).toHaveValue("");
});

test("tutor mocks: a valid ?subject= is applied on load", async () => {
  mockApi(twoSubjectMocks);
  renderAt(<TutorMocksPage />, "/?subject=1");
  expect(await screen.findByRole("heading", { name: "Chemistry" })).toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: "Biology" })).toBeNull();
});

test("tutor mocks: one subject renders its heading and no picker", async () => {
  mockApi({ subjects: [chem, bio], assessments: [assessment(1, 1, "Chem mock A")] });
  renderAt(<TutorMocksPage />);
  expect(await screen.findByRole("heading", { name: "Chemistry" })).toBeInTheDocument();
  expect(screen.queryByLabelText("Subject")).toBeNull();
});

const twoSubjectPapers = {
  subjects: [chem, bio],
  papers: [paper(1, 1, "Chem paper 1"), paper(2, 2, "Bio paper 1")],
};

test("tutor past papers: grouped under subject headings, picker narrows and sets the param", async () => {
  mockApi(twoSubjectPapers);
  renderAt(<TutorPastPapersPage />);
  const bio = await screen.findByRole("region", { name: "Biology" });
  expect(within(bio).getByText("Bio paper 1")).toBeInTheDocument();
  expect(within(screen.getByRole("region", { name: "Chemistry" })).getByText("Chem paper 1"));

  // The picker in the list is the second "Subject" control; the upload form has the first.
  const picker = screen.getAllByLabelText("Subject").at(-1)!;
  fireEvent.change(picker, { target: { value: "1" } });
  expect(screen.getByTestId("search")).toHaveTextContent("?subject=1");
  expect(screen.queryByRole("region", { name: "Biology" })).toBeNull();
  // The upload form's own subject was empty, so it follows the picked subject.
  expect(screen.getAllByLabelText("Subject")[0]).toHaveValue("1");
});

test("tutor past papers: a stale ?subject= falls back to all, one subject has no picker", async () => {
  mockApi(twoSubjectPapers);
  const first = renderAt(<TutorPastPapersPage />, "/?subject=77");
  expect(await screen.findByRole("region", { name: "Biology" })).toBeInTheDocument();
  expect(screen.getByRole("region", { name: "Chemistry" })).toBeInTheDocument();
  first.unmount();

  mockApi({ subjects: [chem, bio], papers: [paper(1, 1, "Chem paper 1")] });
  renderAt(<TutorPastPapersPage />);
  expect(await screen.findByRole("region", { name: "Chemistry" })).toBeInTheDocument();
  // Only the upload form's subject select remains.
  expect(screen.getAllByLabelText("Subject")).toHaveLength(1);
});

test("student mocks: several subjects get a heading each; one subject gets none", async () => {
  const mock = (id: number, subject_id: number, title: string) => ({
    id,
    subject_id,
    title,
    duration_minutes: 60,
    total_marks: 50,
    my_submission_status: null,
  });
  mockApi({ subjects: [chem, bio], assessments: [mock(1, 1, "Chem M"), mock(2, 2, "Bio M")] });
  const first = renderAt(<StudentMocksPage />);
  expect(await screen.findByRole("heading", { name: "Biology" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Chemistry" })).toBeInTheDocument();
  first.unmount();

  mockApi({ subjects: [chem, bio], assessments: [mock(1, 1, "Chem M")] });
  renderAt(<StudentMocksPage />);
  expect(await screen.findByText("Chem M")).toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: "Chemistry" })).toBeNull();
});
