import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, test, vi } from "vitest";
import StudentHomePage from "../student/StudentHomePage";
import type { SubjectReadiness } from "../api/readiness";
import type { StudentAssignment } from "../api/homework";

/* The student's home. The number this page used to open with — one "Overall
   readiness" percentage averaged across subjects with different scales,
   coverage and boundaries — was arithmetically meaningless and was the first
   thing a student read every day. These tests are what keeps it gone. */

function subject(over: Partial<SubjectReadiness> = {}): SubjectReadiness {
  return {
    subject_id: 1,
    subject_name: "Chemistry",
    exam_board: "Edexcel IGCSE",
    grade_scale: "9-1",
    score: 74,
    predicted_grade: "7",
    status: "on_track",
    averaging_score: null,
    averaging_grade: null,
    marked_piece_count: 0,
    direction: "up",
    month_delta: null,
    topics_with_evidence: 0,
    topic_count: 0,
    topics: [],
    weak_topics: [],
    engine: "v2",
    is_updating: false,
    computed_at: null,
    rationale: null,
    recommended_revision: null,
    ...over,
  };
}

function assignment(over: Partial<StudentAssignment> = {}): StudentAssignment {
  return {
    id: 1,
    title: "Moles, p.2",
    instructions: null,
    due_at: null,
    subject_name: "Chemistry",
    group_name: "Chem Y10",
    question_count: 4,
    total_marks: 18,
    submission_status: "not_submitted",
    is_open: true,
    my_total: null,
    finalized_at: null,
    highest_in_class: false,
    ...over,
  };
}

function stubFetch(subjects: SubjectReadiness[], assignments: StudentAssignment[]) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200 });
      if (url.includes("/readiness/me")) {
        return json({ student_id: 1, student_name: "Sara", subjects });
      }
      if (url.includes("/me/assignments")) return json(assignments);
      return json([]);
    }),
  );
}

function renderHome() {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter>
        <StudentHomePage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

test("no cross-subject aggregate is computed", async () => {
  // Two subjects whose mean would be a plausible-looking 61. If any element
  // ever renders that number, an aggregate has come back.
  stubFetch(
    [subject({ score: 74 }), subject({ subject_id: 2, subject_name: "Maths", score: 48 })],
    [],
  );
  const { container } = renderHome();

  await screen.findByText("74");
  expect(screen.getByText("48")).toBeInTheDocument();
  expect(container.textContent).not.toMatch(/\b61\b/);
  expect(screen.queryByText(/overall readiness/i)).not.toBeInTheDocument();
});

test("DO precedes YOU DID in DOM order", async () => {
  stubFetch(
    [subject()],
    [
      assignment({ id: 1 }),
      assignment({
        id: 2,
        title: "Transport",
        submission_status: "marked",
        my_total: 14,
        finalized_at: new Date().toISOString(),
      }),
    ],
  );
  const { container } = renderHome();

  await screen.findByText("Do");
  const headings = [...container.querySelectorAll("h3")].map((h) => h.textContent);
  expect(headings.indexOf("Do")).toBeLessThan(headings.indexOf("You did"));
});

test("a subject without evidence renders words, not a zero", async () => {
  stubFetch([subject({ score: null, predicted_grade: null, status: null, direction: null })], []);
  const { container } = renderHome();

  expect(await screen.findByText("not enough data yet")).toBeInTheDocument();
  expect(container.textContent).not.toMatch(/Chemistry\s*0/);
});

test("a single readiness point renders no arrow", async () => {
  // direction null = fewer than two points. "→" would be a claim.
  stubFetch([subject({ direction: null })], []);
  renderHome();

  await screen.findByText("74");
  expect(screen.queryByText("→")).not.toBeInTheDocument();
  expect(screen.queryByLabelText(/Trending/)).not.toBeInTheDocument();
});

test("a subject that has moved is reported with the same sign as its arrow", async () => {
  stubFetch([subject({ direction: "up", month_delta: 6 })], []);
  renderHome();
  expect(await screen.findByText(/Chemistry up 6 this month/)).toBeInTheDocument();
});

test("movement below the noise band is not announced", async () => {
  // The backend calls a change this small "flat"; the home must not call it a
  // win, or the two disagree on one screen.
  stubFetch([subject({ direction: "flat", month_delta: 2 })], []);
  renderHome();
  await screen.findByText("74");
  expect(screen.queryByText(/this month/)).not.toBeInTheDocument();
});

test("the cleared state offers exactly one action, and it is past papers", async () => {
  stubFetch([subject()], []);
  renderHome();

  expect(await screen.findByText("You're clear. Nothing due.")).toBeInTheDocument();
  expect(screen.getByText("Sit a past paper")).toBeInTheDocument();
  // There is no practice, quiz or revision generator behind any other verb, and
  // a control with nothing behind it is worse than no control.
  const links = [...document.querySelectorAll("a")].map((a) => a.getAttribute("href"));
  expect(links).toContain("/student/past-papers");
  expect(screen.queryByText(/practi[cs]e/i)).not.toBeInTheDocument();
  expect(screen.queryByText(/quiz/i)).not.toBeInTheDocument();
});

test("a closed, unsubmitted assignment is not offered as work to start", async () => {
  // The list carries closed assignments so their marks stay in history, but a
  // closed piece cannot be started — it must not get a Start link or count
  // toward the day's verdict (Qodo).
  stubFetch([subject()], [assignment({ is_open: false, submission_status: "not_submitted" })]);
  renderHome();
  expect(await screen.findByText("You're clear. Nothing due.")).toBeInTheDocument();
  expect(screen.queryByText("Start →")).not.toBeInTheDocument();
});

test("work due suppresses the cleared-state offer", async () => {
  stubFetch([subject()], [assignment()]);
  renderHome();
  expect(await screen.findByText("One thing to do today.")).toBeInTheDocument();
  expect(screen.queryByText("If you want")).not.toBeInTheDocument();
});

test("an empty YOU DID is not rendered as a heading over nothing", async () => {
  stubFetch([subject({ month_delta: null })], [assignment()]);
  renderHome();
  await screen.findByText("Do");
  await waitFor(() => expect(screen.queryByText("You did")).not.toBeInTheDocument());
});

test("the achievement event is attached to the piece it happened on", async () => {
  stubFetch(
    [subject()],
    [
      assignment({
        submission_status: "marked",
        my_total: 17,
        total_marks: 18,
        finalized_at: new Date().toISOString(),
        highest_in_class: true,
      }),
    ],
  );
  renderHome();
  expect(await screen.findByText("highest in your class on this")).toBeInTheDocument();
});

test("no standing is rendered anywhere on the home", async () => {
  // Peer comparison here is an achievement event and never a rank: a standing
  // a student meets daily becomes a standing whose disappearance is the
  // message.
  stubFetch([subject()], [assignment({ submission_status: "marked", my_total: 12 })]);
  const { container } = renderHome();
  await screen.findByText("74");
  expect(container.textContent).not.toMatch(/\d+(st|nd|rd|th) of \d+/);
  expect(container.textContent).not.toMatch(/class average/i);
});
