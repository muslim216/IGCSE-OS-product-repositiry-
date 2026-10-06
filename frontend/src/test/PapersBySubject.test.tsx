import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import TutorMocksPage from "../tutor/MocksPage";
import TutorPastPapersPage from "../tutor/PastPapersPage";
import StudentMocksPage from "../student/MocksPage";
import StudentPastPapersPage from "../student/PastPapersPage";

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

const studentMock = (id: number, subject_id: number, title: string) => ({
  id,
  subject_id,
  title,
  duration_minutes: 60,
  total_marks: 50,
  my_submission_status: null,
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

interface Api {
  /** "ok" by default; "fail" answers 500; "pending" never answers. */
  subjects?: unknown[] | "fail" | "pending";
  assessments?: unknown[];
  papers?: unknown[];
  created?: unknown;
}

function mockApi(data: Api) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/subjects")) {
        if (data.subjects === "pending") return new Promise<Response>(() => {});
        if (data.subjects === "fail") return new Response("{}", { status: 500 });
        return new Response(JSON.stringify(data.subjects ?? []), { status: 200 });
      }
      if (init?.method === "POST" && url.includes("/past-papers")) {
        return new Response(JSON.stringify(data.created), { status: 201 });
      }
      const body =
        url.includes("/assessments") || url.includes("/mocks")
          ? (data.assessments ?? [])
          : url.includes("/past-papers")
            ? (data.papers ?? [])
            : [];
      return new Response(JSON.stringify(body), { status: 200 });
    }),
  );
}

function Where() {
  const { search, hash } = useLocation();
  return (
    <>
      <span data-testid="search">{search}</span>
      <span data-testid="hash">{hash}</span>
    </>
  );
}

function renderAt(node: React.ReactNode, entry = "/") {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter initialEntries={[entry]}>
        {node}
        <Where />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/** The element holding one subject's heading and its list. */
const groupOf = (name: string) =>
  screen.getByRole("heading", { name }).parentElement!.parentElement!;

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
  expect(within(groupOf("Biology")).getByText("Bio mock A")).toBeInTheDocument();
  expect(within(groupOf("Biology")).queryByText("Chem mock A")).toBeNull();
  const chemItems = within(groupOf("Chemistry")).getAllByRole("listitem");
  expect(chemItems.map((li) => li.textContent)).toEqual([
    expect.stringContaining("Chem mock A"),
    expect.stringContaining("Chem mock B"),
  ]);
});

test("tutor mocks: picking a subject narrows the list, writes ?subject= and says what is shown", async () => {
  mockApi(twoSubjectMocks);
  renderAt(<TutorMocksPage />);
  await screen.findByRole("heading", { name: "Chemistry" });
  // Nothing is announced on arrival.
  expect(screen.getByRole("status")).toBeEmptyDOMElement();
  fireEvent.change(screen.getByLabelText("Show subject"), { target: { value: "1" } });
  expect(screen.getByTestId("search")).toHaveTextContent("?subject=1");
  expect(screen.queryByRole("heading", { name: "Biology" })).toBeNull();
  expect(screen.getByRole("status")).toHaveTextContent("Showing 2 mocks and tests in Chemistry");
  fireEvent.change(screen.getByLabelText("Show subject"), { target: { value: "2" } });
  expect(screen.getByRole("status")).toHaveTextContent("Showing 1 mock or test in Biology");
  fireEvent.change(screen.getByLabelText("Show subject"), { target: { value: "" } });
  expect(screen.getByTestId("search")).toHaveTextContent(/^$/);
  expect(screen.getByRole("status")).toHaveTextContent("Showing all subjects");
  expect(screen.getByRole("heading", { name: "Chemistry" })).toBeInTheDocument();
});

test("tutor mocks: a stale ?subject= falls back to all subjects", async () => {
  mockApi(twoSubjectMocks);
  renderAt(<TutorMocksPage />, "/?subject=999");
  expect(await screen.findByRole("heading", { name: "Chemistry" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Biology" })).toBeInTheDocument();
  expect(screen.getByLabelText("Show subject")).toHaveValue("");
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
  expect(screen.queryByLabelText("Show subject")).toBeNull();
});

test("tutor mocks: unknown subjects collapse into one 'Other subject' group and one option", async () => {
  mockApi({
    subjects: [chem],
    assessments: [
      assessment(1, 1, "Chem A"),
      assessment(2, 8, "Lost A"),
      assessment(3, 9, "Lost B"),
    ],
  });
  renderAt(<TutorMocksPage />);
  await screen.findByRole("heading", { name: "Chemistry" });
  expect(screen.getAllByRole("heading", { name: "Other subject" })).toHaveLength(1);
  expect(within(groupOf("Other subject")).getAllByRole("listitem")).toHaveLength(2);
  const options = within(screen.getByLabelText("Show subject")).getAllByRole("option");
  expect(options.map((o) => o.textContent)).toEqual([
    "All subjects",
    "Chemistry (Cambridge)",
    "Other subject",
  ]);
});

test("tutor mocks: while subjects load, or if they fail, the list is flat — no headings, no picker", async () => {
  for (const subjects of ["pending", "fail"] as const) {
    mockApi({ subjects, assessments: [assessment(1, 1, "Chem A"), assessment(2, 2, "Bio A")] });
    const view = renderAt(<TutorMocksPage />);
    expect(await screen.findByText("Chem A")).toBeInTheDocument();
    expect(screen.getByText("Bio A")).toBeInTheDocument();
    // Let a failed request settle before asserting what it did not produce.
    await new Promise((r) => setTimeout(r, 20));
    expect(screen.queryByRole("heading", { name: "Other subject" })).toBeNull();
    expect(screen.queryByLabelText("Show subject")).toBeNull();
    view.unmount();
  }
});

test("tutor mocks: heading order is h1, h2 sections, h3 subjects", async () => {
  mockApi(twoSubjectMocks);
  renderAt(<TutorMocksPage />);
  await screen.findByRole("heading", { name: "Chemistry" });
  expect(screen.getByRole("heading", { level: 1 })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Enter marks", level: 2 })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Recorded so far", level: 2 })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Chemistry", level: 3 })).toBeInTheDocument();
});

const twoSubjectPapers = {
  subjects: [chem, bio],
  papers: [paper(1, 1, "Chem paper 1"), paper(2, 2, "Bio paper 1")],
};

test("tutor past papers: grouped, picker narrows and sets the param; form follows until touched", async () => {
  mockApi(twoSubjectPapers);
  renderAt(<TutorPastPapersPage />);
  await screen.findByRole("heading", { name: "Biology" });
  expect(within(groupOf("Biology")).getByText("Bio paper 1")).toBeInTheDocument();
  expect(within(groupOf("Chemistry")).getByText("Chem paper 1")).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Add a paper", level: 2 })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Your papers", level: 2 })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Chemistry", level: 3 })).toBeInTheDocument();

  fireEvent.change(screen.getByLabelText("Show subject"), { target: { value: "1" } });
  expect(screen.getByTestId("search")).toHaveTextContent("?subject=1");
  expect(screen.queryByRole("heading", { name: "Biology" })).toBeNull();
  expect(screen.getByRole("status")).toHaveTextContent("Showing 1 paper in Chemistry");
  expect(screen.getByLabelText("Subject")).toHaveValue("1");
});

test("tutor past papers: the form's subject can be cleared while a filter is active", async () => {
  mockApi(twoSubjectPapers);
  renderAt(<TutorPastPapersPage />, "/?subject=1");
  await screen.findByRole("heading", { name: "Chemistry" });
  const form = screen.getByLabelText("Subject");
  expect(form).toHaveValue("1");
  fireEvent.change(form, { target: { value: "" } });
  expect(form).toHaveValue("");
  fireEvent.change(form, { target: { value: "2" } });
  expect(form).toHaveValue("2");
});

test("tutor past papers: uploading to another subject moves the filter to it", async () => {
  mockApi({ ...twoSubjectPapers, created: paper(3, 2, "Bio paper 2") });
  const { container } = renderAt(<TutorPastPapersPage />, "/?subject=1");
  await screen.findByRole("heading", { name: "Chemistry" });
  fireEvent.change(screen.getByLabelText("Subject"), { target: { value: "2" } });
  fireEvent.change(container.querySelector('input[type="file"]')!, {
    target: { files: [new File(["x"], "p.pdf", { type: "application/pdf" })] },
  });
  fireEvent.click(screen.getByRole("button", { name: "Add past paper" }));
  await waitFor(() => expect(screen.getByTestId("search")).toHaveTextContent("?subject=2"));
});

test("tutor past papers: a #paper- link to a row the filter hides clears the filter and focuses it", async () => {
  mockApi(twoSubjectPapers);
  renderAt(<TutorPastPapersPage />, "/?subject=1#paper-2");
  await waitFor(() => expect(document.activeElement).toBe(document.getElementById("paper-2")));
  expect(screen.getByTestId("search")).toHaveTextContent(/^$/);
  expect(screen.getByTestId("hash")).toHaveTextContent("#paper-2");
});

test("tutor past papers: changing the filter keeps the hash", async () => {
  mockApi(twoSubjectPapers);
  renderAt(<TutorPastPapersPage />, "/#paper-1");
  await screen.findByRole("heading", { name: "Biology" });
  fireEvent.change(screen.getByLabelText("Show subject"), { target: { value: "1" } });
  expect(screen.getByTestId("hash")).toHaveTextContent("#paper-1");
});

test("tutor past papers: a stale ?subject= falls back to all, one subject has no picker", async () => {
  mockApi(twoSubjectPapers);
  const first = renderAt(<TutorPastPapersPage />, "/?subject=77");
  expect(await screen.findByRole("heading", { name: "Biology" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Chemistry" })).toBeInTheDocument();
  first.unmount();

  mockApi({ subjects: [chem, bio], papers: [paper(1, 1, "Chem paper 1")] });
  renderAt(<TutorPastPapersPage />);
  expect(await screen.findByRole("heading", { name: "Chemistry" })).toBeInTheDocument();
  expect(screen.queryByLabelText("Show subject")).toBeNull();
});

test("tutor past papers: subjects failing leaves a flat list", async () => {
  mockApi({ subjects: "fail", papers: twoSubjectPapers.papers });
  renderAt(<TutorPastPapersPage />);
  expect(await screen.findByText("Chem paper 1")).toBeInTheDocument();
  await new Promise((r) => setTimeout(r, 20));
  expect(screen.queryByRole("heading", { name: "Other subject" })).toBeNull();
  expect(screen.queryByLabelText("Show subject")).toBeNull();
});

test("student mocks: several subjects get an h2 each; one subject gets none", async () => {
  mockApi({
    subjects: [chem, bio],
    assessments: [studentMock(1, 1, "Chem M"), studentMock(2, 2, "Bio M")],
  });
  const first = renderAt(<StudentMocksPage />);
  expect(await screen.findByRole("heading", { name: "Biology", level: 2 })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Chemistry", level: 2 })).toBeInTheDocument();
  expect(screen.getByRole("heading", { level: 1 })).toBeInTheDocument();
  first.unmount();

  mockApi({ subjects: [chem, bio], assessments: [studentMock(1, 1, "Chem M")] });
  renderAt(<StudentMocksPage />);
  expect(await screen.findByText("Chem M")).toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: "Chemistry" })).toBeNull();
});

test("student pages: while subjects load or fail, the list is flat with no 'Other subject'", async () => {
  for (const subjects of ["pending", "fail"] as const) {
    mockApi({
      subjects,
      assessments: [studentMock(1, 1, "Chem M"), studentMock(2, 2, "Bio M")],
      papers: [paper(1, 1, "Chem paper"), paper(2, 2, "Bio paper")],
    });
    const mocks = renderAt(<StudentMocksPage />);
    expect(await screen.findByText("Chem M")).toBeInTheDocument();
    await new Promise((r) => setTimeout(r, 20));
    expect(screen.queryByRole("heading", { name: "Other subject" })).toBeNull();
    mocks.unmount();

    const papers = renderAt(<StudentPastPapersPage />);
    expect(await screen.findByText("Chem paper")).toBeInTheDocument();
    await new Promise((r) => setTimeout(r, 20));
    expect(screen.queryByRole("heading", { name: "Other subject" })).toBeNull();
    papers.unmount();
  }
});

test("student past papers: several subjects get an h2 each", async () => {
  mockApi(twoSubjectPapers);
  renderAt(<StudentPastPapersPage />);
  expect(await screen.findByRole("heading", { name: "Biology", level: 2 })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Chemistry", level: 2 })).toBeInTheDocument();
});
