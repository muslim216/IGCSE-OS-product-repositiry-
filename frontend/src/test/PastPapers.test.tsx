import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
  // `title` and `display_title` differ deliberately. Set to the same string,
  // every assertion below passes whichever of the two the page renders — and a
  // page switched to `title` would silently drop the "Untitled paper" fallback
  // for papers still extracting. Only the display field is ever asserted.
  title: "RAW TITLE — no component should render this",
  display_title: "Cambridge IGCSE Chemistry 0620/21 Paper 2 Multiple Choice",
  session_label: "November 2026",
  paper_number: "Paper 1",
  total_marks: 80,
  duration_minutes: 90,
  paper_name: "paper.pdf",
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
  // The mark scheme is optional now, and the form says what skipping it costs
  // rather than blocking the upload.
  expect(screen.getByText(/no mark is finalized for you/)).toBeInTheDocument();
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

test("a failed paper's advice never claims removing it takes it away from students", async () => {
  // Remove only hides a paper from the tutor's own list — students keep it.
  // "Remove it and upload it again" left the unreadable copy on every
  // student's list beside the new one; the fixes now work on the paper itself.
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
  expect(await screen.findByText(/Students still see this one/)).toBeInTheDocument();
  expect(screen.queryByText(/Remove it and upload it again/)).not.toBeInTheDocument();
});

test("the tutor sees a mark scheme link only when there is one to open", async () => {
  // `mark_scheme_name` is the only signal a scheme file exists; the download
  // route 404s without one, so linking unconditionally sent tutors to a dead
  // link on every paper uploaded without a scheme.
  mockFetch([{ ...paper, mark_scheme_name: "ms.pdf" }]);
  const { unmount } = renderPage(<TutorPastPapersPage />);
  expect(await screen.findByText("Mark scheme")).toBeInTheDocument();
  expect(screen.queryByText("No mark scheme")).not.toBeInTheDocument();
  unmount();

  mockFetch([paper]);
  renderPage(<TutorPastPapersPage />);
  expect(await screen.findByText("No mark scheme")).toBeInTheDocument();
  expect(screen.queryByText("Mark scheme")).not.toBeInTheDocument();
});

test("an upload with no mark scheme chosen sends no mark scheme field", async () => {
  // An empty part would arrive as an UploadFile with a blank filename, which
  // the handler treats as absent anyway — but sending nothing is what keeps
  // the two ends honest about "optional".
  const calls: FormData[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.body instanceof FormData) calls.push(init.body);
      return new Response(JSON.stringify({}), { status: 200 });
    }),
  );
  const { uploadPastPaper } = await import("../api/pastPapers");

  await uploadPastPaper({
    subject_id: 1,
    paper: new File(["x"], "paper.pdf", { type: "application/pdf" }),
  });
  expect(calls[0].has("mark_scheme")).toBe(false);

  await uploadPastPaper({
    subject_id: 1,
    paper: new File(["x"], "paper.pdf", { type: "application/pdf" }),
    mark_scheme: new File(["y"], "ms.pdf", { type: "application/pdf" }),
  });
  expect(calls[1].has("mark_scheme")).toBe(true);
});

/* An unreadable paper is the tutor's to check and fix (owner decision,
   2026-10-02): the to-do list links here, and the fix is on the paper. */

const unreadable = {
  ...paper,
  title: null,
  display_title: "Untitled paper",
  paper_name: "0620_w26_qp_21.pdf",
  question_count: 0,
  extraction_error: "No questions were found in the past paper",
};

type Call = { method: string; url: string; body?: BodyInit | null };

/** The unreadable paper once a fix has been accepted: its read is under way. */
const beingRead = { ...unreadable, extraction_error: null };

function recordFetch(papers: unknown[], detail?: unknown) {
  const calls: Call[] = [];
  let fixed = false;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      calls.push({ method, url, body: init?.body });
      const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200 });
      if (method !== "GET") {
        fixed = true;
        return json(beingRead);
      }
      if (/\/past-papers\/\d+$/.test(url)) return json(detail);
      if (url.includes("/past-papers"))
        return json(fixed ? papers.map((p) => (p === unreadable ? beingRead : p)) : papers);
      return json([]);
    }),
  );
  return calls;
}

test("a paper that couldn't be read names its file and offers both fixes", async () => {
  recordFetch([unreadable]);
  renderPage(<TutorPastPapersPage />);
  // Unread means unnamed; the file is what the tutor will recognise.
  expect(await screen.findByText("0620_w26_qp_21.pdf")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /^Try again/ })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /^Upload a clearer copy/ })).toBeInTheDocument();
  // Students are told about, not left out of, the explanation.
  expect(screen.getByText(/marked once it's read/)).toBeInTheDocument();
});

test("a paper that was read offers no fix", async () => {
  recordFetch([paper]);
  renderPage(<TutorPastPapersPage />);
  await screen.findByText(paper.display_title);
  expect(screen.queryByRole("button", { name: /^Try again/ })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /^Upload a clearer copy/ })).not.toBeInTheDocument();
});

test("Try again asks for the same paper to be read once more", async () => {
  const calls = recordFetch([unreadable]);
  renderPage(<TutorPastPapersPage />);
  fireEvent.click(await screen.findByRole("button", { name: /^Try again/ }));
  await waitFor(() =>
    expect(calls).toContainEqual(
      expect.objectContaining({ method: "POST", url: "/api/v1/past-papers/1/retry-extraction" }),
    ),
  );
});

test("a clearer copy replaces the unreadable one rather than sitting beside it", async () => {
  const calls = recordFetch([unreadable]);
  renderPage(<TutorPastPapersPage />);
  fireEvent.click(await screen.findByRole("button", { name: /^Upload a clearer copy/ }));
  const dialog = await screen.findByRole("dialog");
  const submit = within(dialog).getByRole("button", { name: "Upload and read it" });
  // Nothing to send until a file is chosen.
  expect(submit).toBeDisabled();

  const file = new File(["%PDF"], "clearer.pdf", { type: "application/pdf" });
  fireEvent.change(dialog.querySelector('input[type="file"]')!, { target: { files: [file] } });
  fireEvent.click(submit);

  await waitFor(() =>
    expect(calls).toContainEqual(
      expect.objectContaining({ method: "PUT", url: "/api/v1/past-papers/1/paper" }),
    ),
  );
  const sent = calls.find((c) => c.method === "PUT")!.body as FormData;
  expect((sent.get("paper") as File).name).toBe("clearer.pdf");
  // No second paper is uploaded alongside: the fix is to this paper.
  expect(calls.some((c) => c.method === "POST" && c.url === "/api/v1/past-papers")).toBe(false);
});

test("a paper waiting on a fix leads the list", async () => {
  // The API sends newest first; the unreadable one is older here.
  recordFetch([{ ...paper, id: 2 }, unreadable]);
  renderPage(<TutorPastPapersPage />);
  await screen.findByText("0620_w26_qp_21.pdf");
  const rows = screen.getAllByRole("listitem").filter((li) => li.id.startsWith("paper-"));
  expect(rows.map((li) => li.id)).toEqual(["paper-1", "paper-2"]);
});

test("the to-do link lands on the paper it names", async () => {
  recordFetch([{ ...paper, id: 2 }, unreadable]);
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter initialEntries={["/tutor/past-papers#paper-1"]}>
        <TutorPastPapersPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  await screen.findByText("0620_w26_qp_21.pdf");
  await waitFor(() => expect(document.activeElement?.id).toBe("paper-1"));
});

test("removing an unreadable paper says its answers can't be marked, not that nobody is affected", async () => {
  recordFetch([unreadable]);
  renderPage(<TutorPastPapersPage />);
  // Named by its file: several unread rows would otherwise all be "Untitled paper".
  fireEvent.click(await screen.findByRole("button", { name: "Remove 0620_w26_qp_21.pdf" }));
  expect(await screen.findByText(/nothing they send for it can be marked/)).toBeInTheDocument();
  expect(screen.queryByText(/is unaffected/)).not.toBeInTheDocument();
});

test("a read paper shows which topics each question's marks count towards", async () => {
  recordFetch([paper], {
    ...paper,
    questions: [
      {
        id: 11,
        number: "1",
        text_summary: "Define an isotope",
        max_marks: 2,
        has_mark_scheme: true,
        topics: [{ id: 5, code: "1.3", title: "Atomic structure", parent_id: null }],
      },
      {
        id: 12,
        number: "2",
        text_summary: "A question on nothing in the syllabus",
        max_marks: 3,
        has_mark_scheme: true,
        topics: [],
      },
    ],
  });
  renderPage(<TutorPastPapersPage />);
  const toggle = await screen.findByRole("button", {
    name: `Questions and topics for ${paper.display_title}`,
  });
  expect(toggle).toHaveAttribute("aria-expanded", "false");
  fireEvent.click(toggle);

  expect(await screen.findByText(/Atomic structure/)).toBeInTheDocument();
  expect(screen.getByText(/No topic/)).toBeInTheDocument();
  // A mark that counts towards nothing is called out, not left to be noticed.
  expect(screen.getByText(/1 question isn't linked to a topic/)).toBeInTheDocument();
});

test("a paper whose fix was accepted stops offering it straight away", async () => {
  // Until the refetch lands, the cached row still offered both fixes, and a
  // second press was refused because the paper was already being read.
  recordFetch([unreadable]);
  renderPage(<TutorPastPapersPage />);
  fireEvent.click(await screen.findByRole("button", { name: /^Try again/ }));
  expect(await screen.findByText(/Reading the questions out of the paper/)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /^Try again/ })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /^Upload a clearer copy/ })).not.toBeInTheDocument();
});
