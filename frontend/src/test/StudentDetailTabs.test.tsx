import { useRef } from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import { MemoryRouter, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, test, vi } from "vitest";
import StudentDetailPage from "../tutor/StudentDetailPage";

/* The student page is a short summary and four tabs (T-041). Every control the
   old single page offered must still exist, in the tab the design gives it. */

let calls: string[] = [];
type Json = Record<string, unknown>;
type StubOpts = {
  readinessStatus?: number;
  subjects?: Json[];
  /** Answers POST /observations; omit for an immediate success. */
  postObservation?: () => Promise<Response>;
  postSeed?: () => Promise<Response>;
  redos?: unknown[];
};

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

function subject(over: Json = {}): Json {
  return {
    subject_id: 5,
    subject_name: "Chemistry",
    exam_board: "CIE",
    grade_scale: "9-1",
    score: 60,
    predicted_grade: "5",
    status: "on_track",
    verdict: { status: "needs_attention", headline: "h", reason_topics: [], next_step: "n" },
    averaging_score: null,
    averaging_grade: null,
    marked_piece_count: 3,
    direction: "up",
    month_delta: null,
    topics_with_evidence: 1,
    topic_count: 2,
    homework_assignment_count: null,
    is_updating: false,
    calculation_failed: false,
    topics: [],
    weak_topics: [],
    ...over,
  };
}

const verdict = (status: string) => ({ status, headline: "h", reason_topics: [], next_step: "n" });

function stub(o: StubOpts = {}) {
  calls = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), "http://localhost");
      calls.push(url.pathname);
      const m = init?.method ?? "GET";
      if (url.pathname === "/api/v1/readiness/students/2") {
        if (o.readinessStatus && o.readinessStatus !== 200)
          return json({ detail: "x" }, o.readinessStatus);
        return json({
          student_id: 2,
          student_name: "Sara",
          subjects: o.subjects ?? [subject()],
        });
      }
      if (url.pathname === "/api/v1/readiness/students/3")
        return json({ student_id: 3, student_name: "Omar", subjects: [] });
      if (m === "POST" && url.pathname === "/api/v1/observations")
        return o.postObservation ? o.postObservation() : json({ id: 1 });
      if (m === "POST" && url.pathname.endsWith("/seed-readiness"))
        return o.postSeed ? o.postSeed() : json({ seeded: 1 });
      if (url.pathname.endsWith("/erasure")) return json(null);
      if (url.pathname.endsWith("/redos")) return json(o.redos ?? []);
      if (url.pathname.includes("/mistakes")) return json({ analysed_questions: 0 });
      if (url.pathname.endsWith("/topics"))
        return json([{ id: 9, code: "1.1", title: "Ionic bonding" }]);
      return json([]);
    }),
  );
}

function Where() {
  const l = useLocation();
  const nav = useNavigate();
  // Every distinct history entry the router has visited: arrowing must add none.
  const visits = useRef(new Set<string>());
  visits.current.add(l.key);
  return (
    <>
      <output data-testid="loc">{l.search}</output>
      <output data-testid="visits">{visits.current.size}</output>
      <button onClick={() => nav(-1)}>history back</button>
      <button onClick={() => nav("/tutor/students/3")}>go to Omar</button>
    </>
  );
}

function renderPage(entry = "/tutor/students/2") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[entry]}>
        <Where />
        <Routes>
          <Route path="/tutor/students/:studentId" element={<StudentDetailPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

const key = (k: string) => fireEvent.keyDown(document.activeElement!, { key: k });
const tab = (name: string) => screen.findByRole("tab", { name });
const selected = () => screen.getByRole("tab", { selected: true }).textContent;

test("four tabs, Progress is the default, and the summary is above them", async () => {
  stub();
  renderPage();
  expect((await screen.findAllByRole("tab")).map((t) => t.textContent)).toEqual([
    "Progress",
    "Work",
    "Notes",
    "About",
  ]);
  expect(selected()).toBe("Progress");
  expect(screen.getByText("Needs attention: Chemistry")).toBeInTheDocument();
  expect(screen.getByRole("tabpanel")).toHaveAccessibleName("Progress");
});

test("?tab=about opens About and an unknown tab falls back to Progress", async () => {
  stub();
  const first = renderPage("/tutor/students/2?tab=about");
  await tab("About");
  expect(selected()).toBe("About");
  first.unmount();
  renderPage("/tutor/students/2?tab=junk&group=3");
  await tab("About");
  expect(selected()).toBe("Progress");
});

test("arrow keys, Home and End only move focus; Enter or a click opens the tab", async () => {
  stub();
  renderPage();
  const progress = await tab("Progress");
  progress.focus();
  key("ArrowRight");
  expect(screen.getByRole("tab", { name: "Work" })).toHaveFocus();
  expect(selected()).toBe("Progress");
  key("End");
  expect(screen.getByRole("tab", { name: "About" })).toHaveFocus();
  key("ArrowRight");
  expect(progress).toHaveFocus();
  key("ArrowLeft");
  expect(screen.getByRole("tab", { name: "About" })).toHaveFocus();
  key("Home");
  expect(progress).toHaveFocus();
  expect(selected()).toBe("Progress");
  // Opening is a click, which is what Enter and Space send to a button.
  key("ArrowRight");
  fireEvent.click(document.activeElement!);
  expect(selected()).toBe("Work");
  expect(screen.getByRole("tab", { name: "Work" })).toHaveAttribute("tabindex", "0");
  expect(progress).toHaveAttribute("tabindex", "-1");
});

test("arrowing across the tabs mounts nothing and adds no history entry", async () => {
  stub();
  renderPage();
  const progress = await tab("Progress");
  await waitFor(() => expect(calls.some((c) => c.includes("/mistakes"))).toBe(true));
  const before = calls.length;
  progress.focus();
  key("ArrowRight");
  key("ArrowRight");
  key("ArrowRight");
  key("Home");
  expect(screen.getByTestId("visits")).toHaveTextContent("1");
  expect(screen.getByTestId("loc")).toHaveTextContent("");
  expect(screen.getByTestId("loc").textContent).toBe("");
  expect(calls.length).toBe(before);
  expect(screen.queryByText(/Starting estimate/)).not.toBeInTheDocument();
});

test("clicking the open tab, or Progress on a bare URL, adds no history entry", async () => {
  stub();
  renderPage();
  fireEvent.click(await tab("Progress"));
  expect(screen.getByTestId("visits")).toHaveTextContent("1");
  expect(screen.getByTestId("loc").textContent).toBe("");
  fireEvent.click(screen.getByRole("tab", { name: "Work" }));
  fireEvent.click(screen.getByRole("tab", { name: "Work" }));
  expect(screen.getByTestId("visits")).toHaveTextContent("2");
});

test("only the selected tab points at a panel, because the others are not rendered", async () => {
  stub();
  renderPage();
  await tab("Progress");
  expect(screen.getByRole("tab", { name: "Progress" })).toHaveAttribute(
    "aria-controls",
    "student-panel-progress",
  );
  for (const n of ["Work", "Notes", "About"])
    expect(screen.getByRole("tab", { name: n })).not.toHaveAttribute("aria-controls");
});

test("switching tabs changes the URL and Back restores the previous tab", async () => {
  stub();
  renderPage("/tutor/students/2?group=3");
  fireEvent.click(await tab("Notes"));
  expect(screen.getByTestId("loc")).toHaveTextContent("tab=notes");
  expect(screen.getByTestId("loc")).toHaveTextContent("group=3");
  fireEvent.click(screen.getByRole("button", { name: "history back" }));
  expect(selected()).toBe("Progress");
});

test("an unsaved note survives a switch to another tab and back", async () => {
  stub();
  renderPage("/tutor/students/2?tab=notes");
  fireEvent.change(await screen.findByLabelText(/What did you notice/), {
    target: { value: "needs more practice" },
  });
  fireEvent.click(screen.getByRole("tab", { name: "About" }));
  fireEvent.click(screen.getByRole("tab", { name: "Notes" }));
  expect(screen.getByLabelText(/What did you notice/)).toHaveValue("needs more practice");
});

const DELETE = /delete/i;

test("delete lives only in About, and everything the old page offered is reachable", async () => {
  stub({
    redos: [
      {
        id: 1,
        work_title: "Bonding quiz",
        previous_final_marks: 3,
        previous_max_marks: 5,
        previous_questions_marked: 2,
        previous_question_count: 2,
        created_at: "2026-11-01T00:00:00Z",
        allowed_by_name: "Tutor",
      },
    ],
  });
  renderPage();
  await tab("Progress");
  // One heading or label per section the old page offered, per tab.
  const where: Record<string, RegExp[]> = {
    Progress: [/^Chemistry$/, /Tutor-entered criteria/, /^Attendance$/, /Mistakes in Chemistry/],
    Work: [/Attempts set aside/, /^Reports$/],
    Notes: [/Starting estimate/, /^Observations$/, /Save estimate/, /Save observation/],
    About: [/^Name$/, /Download this student/, /Delete/, /^Messages$/, /Linked parents/],
  };
  for (const [name, patterns] of Object.entries(where)) {
    fireEvent.click(screen.getByRole("tab", { name }));
    const panel = screen.getByRole("tabpanel");
    for (const p of patterns) {
      expect(
        (await within(panel).findAllByText(p, {}, { timeout: 2000 })).length,
        `${name}: ${p}`,
      ).toBeGreaterThan(0);
    }
    const hasDelete = within(panel).queryAllByRole("button", { name: DELETE }).length > 0;
    expect(hasDelete, name).toBe(name === "About");
    expect(screen.queryAllByRole("button", { name: DELETE }).length > 0, name).toBe(
      name === "About",
    );
  }
});

test("a student that does not exist still says so", async () => {
  stub({ readinessStatus: 404 });
  renderPage();
  expect(await screen.findByText("We couldn't find that student")).toBeInTheDocument();
  expect(screen.queryByRole("tab")).not.toBeInTheDocument();
});

test("a closed tab asks for nothing", async () => {
  stub();
  renderPage();
  await tab("Progress");
  await waitFor(() => expect(calls.some((c) => c.includes("/mistakes"))).toBe(true));
  for (const closed of ["/reports", "/redos", "/observations", "/topics", "/contacts", "/erasure"])
    expect(
      calls.some((c) => c.includes(closed)),
      closed,
    ).toBe(false);
  expect(calls.some((c) => c.endsWith("/parents"))).toBe(false);
});

test("a starting estimate typed in Notes survives a trip to About and back", async () => {
  stub();
  renderPage("/tutor/students/2?tab=notes");
  const topic = await screen.findByLabelText(/Topic to estimate/);
  await screen.findAllByRole("option", { name: /Ionic bonding/ });
  fireEvent.change(topic, { target: { value: "9" } });
  fireEvent.change(screen.getByLabelText(/Estimated percentage/), { target: { value: "70" } });
  fireEvent.click(screen.getByRole("tab", { name: "About" }));
  fireEvent.click(screen.getByRole("tab", { name: "Notes" }));
  expect(screen.getByLabelText(/Estimated percentage/)).toHaveValue(70);
  await screen.findAllByRole("option", { name: /Ionic bonding/ });
  expect(screen.getByLabelText(/Topic to estimate/)).toHaveValue("9");
});

function deferred() {
  let resolve!: (r: Response) => void;
  const promise = new Promise<Response>((r) => (resolve = r));
  return { promise, resolve };
}

test("a slow observation save is still pending after a tab switch, so it cannot be sent twice", async () => {
  const d = deferred();
  stub({ postObservation: () => d.promise });
  renderPage("/tutor/students/2?tab=notes");
  fireEvent.change(await screen.findByLabelText(/What did you notice/), {
    target: { value: "needs more practice" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save observation" }));
  await waitFor(() =>
    expect(screen.getByRole("button", { name: /Save observation/ })).toBeDisabled(),
  );
  fireEvent.click(screen.getByRole("tab", { name: "About" }));
  fireEvent.click(screen.getByRole("tab", { name: "Notes" }));
  expect(screen.getByRole("button", { name: /Save observation/ })).toBeDisabled();
  d.resolve(json({ id: 1 }));
  await waitFor(() =>
    expect(screen.getByRole("button", { name: /Save observation/ })).toBeEnabled(),
  );
  expect(screen.getByLabelText(/What did you notice/)).toHaveValue("");
});

test("a failed observation save keeps its error for when the tutor comes back", async () => {
  stub({ postObservation: async () => json({ detail: "no" }, 500) });
  renderPage("/tutor/students/2?tab=notes");
  fireEvent.change(await screen.findByLabelText(/What did you notice/), {
    target: { value: "needs more practice" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save observation" }));
  await screen.findByText("Could not save the observation.");
  fireEvent.click(screen.getByRole("tab", { name: "About" }));
  fireEvent.click(screen.getByRole("tab", { name: "Notes" }));
  expect(screen.getByText("Could not save the observation.")).toBeInTheDocument();
  expect(screen.getByLabelText(/What did you notice/)).toHaveValue("needs more practice");
});

test("a slow estimate save stays pending across a tab switch, then says it saved", async () => {
  const d = deferred();
  stub({ postSeed: () => d.promise });
  renderPage("/tutor/students/2?tab=notes");
  await screen.findAllByRole("option", { name: /Ionic bonding/ });
  fireEvent.change(screen.getByLabelText(/Topic to estimate/), { target: { value: "9" } });
  fireEvent.change(screen.getByLabelText(/Estimated percentage/), { target: { value: "70" } });
  fireEvent.click(screen.getByRole("button", { name: "Save estimate" }));
  await waitFor(() => expect(screen.getByRole("button", { name: /Save estimate/ })).toBeDisabled());
  fireEvent.click(screen.getByRole("tab", { name: "About" }));
  d.resolve(json({ seeded: 1 }));
  await waitFor(() => expect(calls.filter((c) => c.endsWith("/seed-readiness")).length).toBe(1));
  fireEvent.click(screen.getByRole("tab", { name: "Notes" }));
  expect(await screen.findByText("Estimate saved.")).toBeInTheDocument();
});

test("a failed estimate save is still reported after a tab switch", async () => {
  stub({ postSeed: async () => json({ detail: "no" }, 500) });
  renderPage("/tutor/students/2?tab=notes");
  await screen.findAllByRole("option", { name: /Ionic bonding/ });
  fireEvent.change(screen.getByLabelText(/Topic to estimate/), { target: { value: "9" } });
  fireEvent.change(screen.getByLabelText(/Estimated percentage/), { target: { value: "70" } });
  fireEvent.click(screen.getByRole("button", { name: "Save estimate" }));
  await screen.findByText("Could not save the estimate.");
  fireEvent.click(screen.getByRole("tab", { name: "About" }));
  fireEvent.click(screen.getByRole("tab", { name: "Notes" }));
  expect(screen.getByText("Could not save the estimate.")).toBeInTheDocument();
});

test("moving to another student starts with empty drafts", async () => {
  stub();
  renderPage("/tutor/students/2?tab=notes");
  fireEvent.change(await screen.findByLabelText(/What did you notice/), {
    target: { value: "about Sara" },
  });
  fireEvent.click(screen.getByRole("button", { name: "go to Omar" }));
  await screen.findByRole("heading", { name: "Omar" });
  fireEvent.click(screen.getByRole("tab", { name: "Notes" }));
  expect(await screen.findByLabelText(/What did you notice/)).toHaveValue("");
});

/* The summary speaks the shared readiness vocabulary (StatusBadge, the subject
   card's grade rules, DirectionMark), never words of its own. */
const summary = () => screen.getByTestId("student-summary");

test("summary keeps at risk apart from needs attention, most urgent first", async () => {
  stub({
    subjects: [
      subject({ subject_id: 5, subject_name: "Chemistry", verdict: verdict("needs_attention") }),
      subject({ subject_id: 6, subject_name: "Physics", verdict: verdict("at_risk") }),
      subject({ subject_id: 7, subject_name: "Maths", verdict: verdict("on_track") }),
    ],
  });
  renderPage();
  await tab("Progress");
  const lines = within(summary())
    .getAllByTestId("summary-attention")
    .map((e) => e.textContent);
  expect(lines).toEqual(["At risk: Physics", "Needs attention: Chemistry"]);
  expect(within(summary()).getByText("At risk: Physics")).toHaveClass("text-risk-600");
  expect(within(summary()).getByText("Needs attention: Chemistry")).toHaveClass("text-warn-700");
  expect(
    within(summary()).queryByText(/Maths$/, { selector: "[data-testid=summary-attention]" }),
  ).toBeNull();
});

test("summary grade follows the subject card: failed, updating, no boundaries, no score", async () => {
  stub({
    subjects: [
      subject({ subject_id: 1, subject_name: "Failed", calculation_failed: true }),
      subject({ subject_id: 2, subject_name: "Busy", is_updating: true }),
      subject({ subject_id: 3, subject_name: "Unbounded", predicted_grade: null }),
      subject({ subject_id: 4, subject_name: "Empty", score: null, predicted_grade: null }),
      subject({ subject_id: 8, subject_name: "Fine" }),
    ],
  });
  renderPage();
  await tab("Progress");
  const line = (n: string) => within(summary()).getByTestId(`summary-subject-${n}`).textContent;
  expect(line("Failed")).toContain("Couldn't be calculated right now");
  expect(line("Failed")).not.toContain("grade 5");
  expect(line("Busy")).toContain("grade 5");
  expect(line("Busy")).toContain("Updating…");
  expect(line("Unbounded")).toContain("no grade boundaries set");
  expect(line("Unbounded")).not.toContain("no grade yet");
  expect(line("Empty")).toContain("no grade yet");
  expect(line("Fine")).toContain("grade 5");
  expect(line("Fine")).not.toContain("Updating");
});

test("summary direction is the shared mark, and absent when there is no trend", async () => {
  stub({
    subjects: [
      subject({ subject_id: 1, subject_name: "Up", direction: "up" }),
      subject({ subject_id: 2, subject_name: "Flat", direction: "flat" }),
      subject({ subject_id: 3, subject_name: "None", direction: null }),
    ],
  });
  renderPage();
  await tab("Progress");
  const s = within(summary());
  expect(within(s.getByTestId("summary-subject-Up")).getByRole("img")).toHaveAccessibleName(
    "Trending up",
  );
  expect(within(s.getByTestId("summary-subject-Flat")).getByRole("img")).toHaveAccessibleName(
    "Trending flat",
  );
  expect(within(s.getByTestId("summary-subject-None")).queryByRole("img")).toBeNull();
  expect(summary().textContent).not.toMatch(/going up|steady|going down/);
});
