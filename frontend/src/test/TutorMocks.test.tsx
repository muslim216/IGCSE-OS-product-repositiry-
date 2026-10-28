import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import MockPage from "../tutor/MockPage";
import MocksPage from "../tutor/MocksPage";
import SubmissionReviewPage from "../tutor/SubmissionReviewPage";

const subject = { id: 1, exam_board: "CAIE", code: "0620", name: "Chemistry", grade_scale: "9-1" };
const klass = {
  id: 5,
  name: "Year 11 Chem",
  subject,
  member_count: 3,
  students_with_evidence: 0,
  published_assignment_count: 0,
  awaiting_review_count: 0,
  next_lesson: null,
};

const mock = {
  id: 9,
  subject_id: 1,
  group_id: null as number | null,
  title: "Year 11 mock",
  type: "mock",
  sat_on: null,
  status: "published",
  total_marks: 60,
  duration_minutes: 90,
  paper_name: "paper.pdf",
  mark_scheme_name: null as string | null,
  extraction_error: null as string | null,
  question_count: 2,
  my_submission_status: null,
};

const detail = {
  ...mock,
  questions: [
    {
      id: 1,
      number: "1",
      text_summary: "Atoms",
      max_marks: 3,
      has_mark_scheme: false,
      topics: [{ id: 4, code: "1.1", title: "Atomic structure" }],
    },
    {
      id: 2,
      number: "2",
      text_summary: "Bonding",
      max_marks: 5,
      has_mark_scheme: false,
      topics: [],
    },
  ],
};

type Call = { method: string; path: string; body: unknown };
let calls: Call[];

/** Routes by path and method; anything unrouted 404s so a wrong request fails. */
function stub(routes: Record<string, () => Response | Promise<Response>>) {
  calls = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = new URL(String(input), "http://localhost").pathname;
      const method = (init?.method ?? "GET").toUpperCase();
      const body =
        init?.body instanceof FormData
          ? init.body
          : init?.body
            ? JSON.parse(String(init.body))
            : null;
      calls.push({ method, path, body });
      const handler = routes[`${method} ${path}`];
      return handler
        ? handler()
        : new Response(JSON.stringify({ detail: "no route" }), { status: 404 });
    }),
  );
}

const json =
  (body: unknown, status = 200) =>
  () =>
    new Response(JSON.stringify(body), { status });

function renderAt(entry: string, routes: React.ReactNode) {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter initialEntries={[entry]}>
        <Routes>{routes}</Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const renderMocks = () =>
  renderAt("/tutor/mocks", <Route path="/tutor/mocks" element={<MocksPage />} />);
const renderMock = () =>
  renderAt("/tutor/mocks/9", <Route path="/tutor/mocks/:mockId" element={<MockPage />} />);

const base = {
  "GET /api/v1/subjects": json([subject]),
  "GET /api/v1/groups": json([klass]),
  "GET /api/v1/assessments": json([]),
};

beforeEach(() => {
  localStorage.setItem("avora-tokens", JSON.stringify({ access_token: "t", token_type: "bearer" }));
});
afterEach(() => {
  localStorage.clear();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

test("the upload form sends its fields and never a class", async () => {
  stub({ ...base, "GET /api/v1/mocks": json([]), "POST /api/v1/mocks": json(mock) });
  const { container } = renderMocks();
  await screen.findByText("No mocks uploaded yet.");

  const add = screen.getByRole("button", { name: "Add mock" });
  expect(add).toBeDisabled();
  await screen.findByRole("option", { name: /Chemistry/ });
  fireEvent.change(screen.getByLabelText("Subject"), { target: { value: "1" } });
  fireEvent.change(screen.getByLabelText("Title"), { target: { value: "Year 11 mock" } });
  fireEvent.change(screen.getByLabelText(/Time allowed/), { target: { value: "90" } });
  fireEvent.change(screen.getByLabelText(/Date it is sat/), { target: { value: "2026-11-02" } });
  const inputs = container.querySelectorAll<HTMLInputElement>('input[type="file"]');
  fireEvent.change(inputs[0], {
    target: { files: [new File(["x"], "paper.pdf", { type: "application/pdf" })] },
  });
  // No scheme chosen: the form says what that costs rather than blocking.
  expect(screen.getByText(/every one waits for you to check/)).toBeInTheDocument();
  await waitFor(() => expect(add).toBeEnabled());
  fireEvent.click(add);

  await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
  const form = calls.find((c) => c.method === "POST")!.body as FormData;
  expect(form.get("subject_id")).toBe("1");
  expect(form.get("title")).toBe("Year 11 mock");
  expect(form.get("duration_minutes")).toBe("90");
  expect(form.get("sat_on")).toBe("2026-11-02");
  expect((form.get("paper") as File).name).toBe("paper.pdf");
  expect(form.has("mark_scheme")).toBe(false);
  expect(form.has("group_id")).toBe(false);
});

test("the list says what each mock is doing, and where it is open", async () => {
  stub({
    ...base,
    "GET /api/v1/mocks": json([
      { ...mock, id: 1, title: "Open one", group_id: 5 },
      { ...mock, id: 2, title: "Closed one" },
      { ...mock, id: 3, title: "Reading one", status: "extracting", question_count: 0 },
      {
        ...mock,
        id: 4,
        title: "Broken one",
        status: "extraction_failed",
        question_count: 0,
        extraction_error: "model unavailable",
      },
    ]),
  });
  renderMocks();
  expect(await screen.findAllByText(/2 questions · 60 marks/)).toHaveLength(2);
  expect(screen.getByText("Open to Year 11 Chem")).toBeInTheDocument();
  expect(screen.getByText("Not open to a class yet")).toBeInTheDocument();
  expect(screen.getByText("Reading the paper…")).toBeInTheDocument();
  expect(screen.getByText(/Couldn't read this paper/)).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Open one" })).toHaveAttribute("href", "/tutor/mocks/1");
});

test("the list polls while a mock is being read and stops when it is read", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  let reads = 0;
  stub({
    ...base,
    "GET /api/v1/mocks": () => {
      reads += 1;
      const row =
        reads === 1
          ? { ...mock, status: "extracting", question_count: 0 }
          : { ...mock, status: "published" };
      return new Response(JSON.stringify([row]));
    },
  });
  renderMocks();
  expect(await screen.findByText("Reading the paper…")).toBeInTheDocument();
  await vi.advanceTimersByTimeAsync(3100);
  expect(await screen.findByText(/2 questions · 60 marks/)).toBeInTheDocument();
  const after = reads;
  await vi.advanceTimersByTimeAsync(7000);
  expect(reads).toBe(after);
});

test("Try again retries the failed mock", async () => {
  let failed = true;
  stub({
    ...base,
    "GET /api/v1/mocks": () =>
      new Response(
        JSON.stringify([
          failed
            ? { ...mock, status: "extraction_failed", question_count: 0, extraction_error: "x" }
            : { ...mock, status: "extracting", question_count: 0 },
        ]),
      ),
    "POST /api/v1/mocks/9/retry-extraction": () => {
      failed = false;
      return new Response(JSON.stringify({ ...mock, status: "extracting", question_count: 0 }));
    },
  });
  renderMocks();
  fireEvent.click(await screen.findByRole("button", { name: /Try again/ }));
  expect(await screen.findByText("Reading the paper…")).toBeInTheDocument();
  expect(calls.filter((c) => c.path.endsWith("/retry-extraction"))).toHaveLength(1);
});

test("the mock page lists the questions with their topics and warns about unlinked ones", async () => {
  stub({
    ...base,
    "GET /api/v1/mocks/9": json(detail),
    "GET /api/v1/mocks/9/results": json([]),
  });
  renderMock();
  expect(await screen.findByText("Atomic structure", { exact: false })).toBeInTheDocument();
  expect(screen.getByText(/1 question isn't linked to a topic/)).toBeInTheDocument();
  expect(screen.getByText(/can't be edited/)).toBeInTheDocument();
  expect(screen.getByText(/No topic/)).toBeInTheDocument();
});

test("opening to a class asks first, then sends the class", async () => {
  stub({
    ...base,
    "GET /api/v1/mocks/9": json(detail),
    "PATCH /api/v1/mocks/9": json({ ...mock, group_id: 5 }),
  });
  renderMock();
  await screen.findByText(/Not open to a class yet/);
  fireEvent.change(await screen.findByLabelText("Class"), { target: { value: "5" } });
  fireEvent.click(screen.getByRole("button", { name: "Open to class" }));
  // Nothing sent until the tutor confirms.
  expect(calls.some((c) => c.method === "PATCH")).toBe(false);
  const dialog = await screen.findByRole("dialog");
  expect(
    within(dialog).getByText(/Students in Year 11 Chem will see this mock now/),
  ).toBeInTheDocument();
  fireEvent.click(within(dialog).getByRole("button", { name: "Open to class" }));
  await waitFor(() =>
    expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({ group_id: 5 }),
  );
});

test("a refused class change shows the server's reason", async () => {
  stub({
    ...base,
    "GET /api/v1/mocks/9": json({ ...detail, group_id: 5 }),
    "GET /api/v1/mocks/9/results": json([]),
    "PATCH /api/v1/mocks/9": json(
      { detail: "This mock already has submissions — its class can't be changed" },
      409,
    ),
  });
  renderMock();
  expect(await screen.findByText("Open to Year 11 Chem")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Change class" }));
  fireEvent.change(await screen.findByLabelText("Class"), { target: { value: "5" } });
  fireEvent.click(screen.getByRole("button", { name: "Open to class" }));
  const dialog = await screen.findByRole("dialog");
  fireEvent.click(within(dialog).getByRole("button", { name: "Open to class" }));
  expect(await within(dialog).findByRole("alert")).toHaveTextContent(
    "This mock already has submissions",
  );
});

test("the results table shows a mark only once it is final, and never a 0 for a missing one", async () => {
  const row = {
    student_id: 1,
    student_name: "",
    submission_id: null as number | null,
    status: "not_started",
    submitted_at: null as string | null,
    submitted_late: false,
    measured_minutes: null as number | null,
    marks_awarded: null as number | null,
    marks_available: null as number | null,
  };
  stub({
    ...base,
    "GET /api/v1/mocks/9": json({ ...detail, group_id: 5 }),
    "GET /api/v1/mocks/9/results": json([
      { ...row, student_id: 1, student_name: "Ana" },
      { ...row, student_id: 2, student_name: "Bo", status: "in_progress" },
      {
        ...row,
        student_id: 3,
        student_name: "Cy",
        status: "handed_in",
        submission_id: 31,
        submitted_at: "2026-11-02T10:00:00Z",
      },
      {
        ...row,
        student_id: 4,
        student_name: "Di",
        status: "marked",
        submission_id: 41,
        submitted_at: "2026-11-02T10:00:00Z",
      },
      {
        ...row,
        student_id: 5,
        student_name: "Ed",
        status: "final",
        submission_id: 51,
        submitted_at: "2026-11-02T10:00:00Z",
        submitted_late: true,
        measured_minutes: 95,
        marks_awarded: 42,
        marks_available: 60,
      },
    ]),
  });
  renderMock();
  const table = await screen.findByRole("table");
  const rowOf = (name: string) => within(table).getByRole("rowheader", { name }).closest("tr")!;
  expect(within(rowOf("Ana")).getByText("Not handed in")).toBeInTheDocument();
  expect(
    within(rowOf("Bo")).getByText("Sitting it now", { selector: "td:nth-child(4)" }),
  ).toBeInTheDocument();
  expect(within(rowOf("Ana")).getByText("Not started")).toBeInTheDocument();
  expect(
    within(rowOf("Bo")).getByText("Sitting it now", { selector: "td:nth-child(2)" }),
  ).toBeInTheDocument();
  expect(within(rowOf("Cy")).getByText("Being marked by the AI")).toBeInTheDocument();
  expect(within(rowOf("Di")).getByText("Waiting for your review")).toBeInTheDocument();
  expect(within(rowOf("Ed")).getByText("42/60")).toBeInTheDocument();
  expect(within(rowOf("Ed")).getByText("Late")).toBeInTheDocument();
  expect(within(rowOf("Ed")).getByText(/1h 35m/)).toBeInTheDocument();
  expect(within(table).queryByText(/^0(\/\d+)?$/)).not.toBeInTheDocument();
  expect(within(rowOf("Ed")).getByRole("link")).toHaveAttribute("href", "/tutor/submissions/51");
  expect(within(rowOf("Ana")).queryByRole("link")).not.toBeInTheDocument();
});

const resultRow = {
  student_id: 1,
  student_name: "Ana",
  submission_id: null as number | null,
  status: "not_started",
  submitted_at: null as string | null,
  submitted_late: false,
  measured_minutes: null as number | null,
  marks_awarded: null as number | null,
  marks_available: null as number | null,
};

test("a real 0 is shown as 0/60; a final row with no marks says so", async () => {
  const final = {
    ...resultRow,
    status: "final",
    submission_id: 7,
    submitted_at: "2026-11-02T10:00:00Z",
  };
  stub({
    ...base,
    "GET /api/v1/mocks/9": json({ ...detail, group_id: 5 }),
    "GET /api/v1/mocks/9/results": json([
      { ...final, student_name: "Zed", marks_awarded: 0, marks_available: 60 },
      { ...final, student_id: 2, student_name: "Nil" },
    ]),
  });
  renderMock();
  const table = await screen.findByRole("table");
  expect(within(table).getByText("0/60")).toBeInTheDocument();
  expect(within(table).getByText("No marks recorded")).toBeInTheDocument();
});

test("the results show an empty state when no student is listed", async () => {
  stub({
    ...base,
    "GET /api/v1/mocks/9": json({ ...detail, group_id: 5 }),
    "GET /api/v1/mocks/9/results": json([]),
  });
  renderMock();
  expect(await screen.findByText("No students to show yet.")).toBeInTheDocument();
});

test("the results poll while a student is mid-mock and stop when none is", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  let reads = 0;
  stub({
    ...base,
    "GET /api/v1/mocks/9": json({ ...detail, group_id: 5 }),
    "GET /api/v1/mocks/9/results": () => {
      reads += 1;
      return new Response(
        JSON.stringify([{ ...resultRow, status: reads === 1 ? "handed_in" : "marked" }]),
      );
    },
  });
  renderMock();
  expect(await screen.findByText("Being marked by the AI")).toBeInTheDocument();
  await vi.advanceTimersByTimeAsync(15100);
  expect(await screen.findByText("Waiting for your review")).toBeInTheDocument();
  const after = reads;
  await vi.advanceTimersByTimeAsync(40000);
  expect(reads).toBe(after);
});

test("a mock id that is not a number is not found, not a skeleton", async () => {
  stub({ ...base });
  renderAt("/tutor/mocks/abc", <Route path="/tutor/mocks/:mockId" element={<MockPage />} />);
  expect(await screen.findByText("We couldn't find that mock")).toBeInTheDocument();
  expect(calls.some((c) => c.path.startsWith("/api/v1/mocks/"))).toBe(false);
});

test("Cancel in the class picker forgets the class that was picked", async () => {
  stub({
    ...base,
    "GET /api/v1/mocks/9": json({ ...detail, group_id: 5 }),
    "GET /api/v1/mocks/9/results": json([]),
  });
  renderMock();
  fireEvent.click(await screen.findByRole("button", { name: "Change class" }));
  fireEvent.change(await screen.findByLabelText("Class"), { target: { value: "5" } });
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  fireEvent.click(await screen.findByRole("button", { name: "Change class" }));
  expect(await screen.findByLabelText("Class")).toHaveValue("");
});

test("a closed mock says Closed, and a published one with no questions says so", async () => {
  stub({
    ...base,
    "GET /api/v1/mocks": json([
      { ...mock, id: 1, title: "Done", status: "closed" },
      { ...mock, id: 2, title: "Empty", question_count: 0 },
    ]),
  });
  renderMocks();
  expect(await screen.findByText("Closed")).toBeInTheDocument();
  expect(screen.getByText(/No questions read/)).toBeInTheDocument();
});

test("a mark scheme is sent when chosen, the hint changes, and success is announced", async () => {
  stub({ ...base, "GET /api/v1/mocks": json([]), "POST /api/v1/mocks": json(mock) });
  const { container } = renderMocks();
  await screen.findByText("No mocks uploaded yet.");
  await screen.findByRole("option", { name: /Chemistry/ });
  fireEvent.change(screen.getByLabelText("Subject"), { target: { value: "1" } });
  fireEvent.change(screen.getByLabelText("Title"), { target: { value: "Year 11 mock" } });
  const inputs = container.querySelectorAll<HTMLInputElement>('input[type="file"]');
  fireEvent.change(inputs[0], {
    target: { files: [new File(["x"], "paper.pdf", { type: "application/pdf" })] },
  });
  fireEvent.change(inputs[1], {
    target: { files: [new File(["y"], "scheme.pdf", { type: "application/pdf" })] },
  });
  expect(screen.queryByText(/every one waits for you to check/)).not.toBeInTheDocument();
  const add = screen.getByRole("button", { name: "Add mock" });
  await waitFor(() => expect(add).toBeEnabled());
  fireEvent.click(add);
  await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
  const form = calls.find((c) => c.method === "POST")!.body as FormData;
  expect((form.get("mark_scheme") as File).name).toBe("scheme.pdf");
  expect(await screen.findByRole("status")).toHaveTextContent("Added. The AI is reading it.");
  // Editing a field starts a fresh attempt.
  fireEvent.change(screen.getByLabelText("Title"), { target: { value: "Next" } });
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
});

test("a failed upload shows its error until a field changes", async () => {
  stub({
    ...base,
    "GET /api/v1/mocks": json([]),
    "POST /api/v1/mocks": json({ detail: "Nope" }, 400),
  });
  const { container } = renderMocks();
  await screen.findByText("No mocks uploaded yet.");
  await screen.findByRole("option", { name: /Chemistry/ });
  fireEvent.change(screen.getByLabelText("Subject"), { target: { value: "1" } });
  fireEvent.change(screen.getByLabelText("Title"), { target: { value: "T" } });
  fireEvent.change(container.querySelectorAll<HTMLInputElement>('input[type="file"]')[0], {
    target: { files: [new File(["x"], "paper.pdf", { type: "application/pdf" })] },
  });
  const add = screen.getByRole("button", { name: "Add mock" });
  await waitFor(() => expect(add).toBeEnabled());
  fireEvent.click(add);
  expect(await screen.findByRole("alert")).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Title"), { target: { value: "T2" } });
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

test("the detail page polls while the paper is read, then stops", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  let reads = 0;
  stub({
    ...base,
    "GET /api/v1/mocks/9": () => {
      reads += 1;
      return new Response(
        JSON.stringify(reads === 1 ? { ...detail, status: "extracting", questions: [] } : detail),
      );
    },
  });
  renderMock();
  expect(
    await screen.findByText("Reading the paper…", { selector: "p.text-ink-500" }),
  ).toBeInTheDocument();
  await vi.advanceTimersByTimeAsync(3100);
  expect(await screen.findByText(/can't be edited/)).toBeInTheDocument();
  const after = reads;
  await vi.advanceTimersByTimeAsync(10000);
  expect(reads).toBe(after);
});

test("Try again on the detail page retries, and shows a refusal", async () => {
  stub({
    ...base,
    "GET /api/v1/mocks/9": json({
      ...detail,
      status: "extraction_failed",
      questions: [],
      extraction_error: "model unavailable",
    }),
    "POST /api/v1/mocks/9/retry-extraction": json({ detail: "Already being read" }, 409),
  });
  renderMock();
  fireEvent.click(await screen.findByRole("button", { name: "Try again" }));
  await waitFor(() =>
    expect(calls.filter((c) => c.path.endsWith("/retry-extraction"))).toHaveLength(1),
  );
  expect(await screen.findByText("Already being read")).toHaveAttribute("role", "alert");
});

/* ---- The review page, for a mock submission --------------------------- */

function stubReview(over: Record<string, unknown>) {
  stub({
    "GET /api/v1/submissions/1": json({
      id: 1,
      assignment_id: null,
      past_paper_id: null,
      mock_id: 9,
      assignment_title: "Year 11 mock",
      student_id: 2,
      student_name: "Sara",
      status: "needs_review",
      ai_error: null,
      submitted_at: "2026-06-01T10:00:00Z",
      files: [],
      typed_answer: null,
      subject_id: 1,
      marks: [],
      bare_question_count: 2,
      mistakes_analysed: true,
      can_redo: false,
      ...over,
    }),
    "GET /api/v1/submissions/review-queue": json([]),
    "GET /api/v1/subjects/1/mistake-categories": json({
      subject_id: 1,
      subject_name: "Chemistry",
      source: "none",
      categories: [],
    }),
  });
  return renderAt(
    "/tutor/submissions/1",
    <Route path="/tutor/submissions/:submissionId" element={<SubmissionReviewPage />} />,
  );
}

test("a late mock submission says how long it took and carries a Late badge", async () => {
  stubReview({ measured_minutes: 95, submitted_late: true });
  expect(await screen.findByText(/Handed in 95 minutes after starting/)).toBeInTheDocument();
  expect(screen.getByText("Late")).toBeInTheDocument();
});

test("an on-time mock submission has no Late badge", async () => {
  stubReview({ measured_minutes: 40, submitted_late: false });
  expect(await screen.findByText(/Handed in 40 minutes after starting/)).toBeInTheDocument();
  expect(screen.queryByText("Late")).not.toBeInTheDocument();
});

test("a mock's unlinked-topic notice points at the mock's page, without promising an edit", async () => {
  stubReview({});
  const link = await screen.findByRole("link", { name: "See the mock's questions" });
  expect(link).toHaveAttribute("href", "/tutor/mocks/9");
  expect(screen.queryByRole("link", { name: "Fix this" })).not.toBeInTheDocument();
});

test("a past-paper submission shows no minutes line even with a measured time", async () => {
  stubReview({ mock_id: null, past_paper_id: 3, measured_minutes: 40 });
  await screen.findByText("Sara", { exact: false });
  expect(screen.queryByText(/minutes after starting/)).not.toBeInTheDocument();
});

test("late with no measured time shows only the Late badge", async () => {
  stubReview({ measured_minutes: null, submitted_late: true });
  expect(await screen.findByText("Late")).toBeInTheDocument();
  expect(screen.queryByText(/after starting/)).not.toBeInTheDocument();
});

test("one minute is singular", async () => {
  stubReview({ measured_minutes: 1, submitted_late: false });
  expect(await screen.findByText(/Handed in 1 minute after starting/)).toBeInTheDocument();
});
