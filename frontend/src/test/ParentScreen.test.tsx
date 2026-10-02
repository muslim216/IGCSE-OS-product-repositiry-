import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, test, vi } from "vitest";
import ParentDashboard from "../parent/ParentDashboard";
import { parentVerdict, whatYouCanDo } from "../lib/parent";
import type { SubjectReadiness } from "../api/readiness";

/* The parent screen is read by people who cannot ask a follow-up question, who
   visit rarely, and who read ambiguity as bad news that then lands on the
   child. Every test here is about one of those three facts. */

function subject(over: Partial<SubjectReadiness> = {}): SubjectReadiness {
  return {
    subject_id: 1,
    subject_name: "Chemistry",
    exam_board: "Edexcel IGCSE",
    grade_scale: "9-1",
    score: 72,
    predicted_grade: "7",
    status: "on_track",
    averaging_score: 64,
    averaging_grade: "6",
    marked_piece_count: 5,
    direction: "up",
    month_delta: null,
    topics_with_evidence: 2,
    topic_count: 4,
    homework_assignment_count: null,
    homework_submitted_count: null,
    topics: [],
    weak_topics: [],
    is_updating: false,
    computed_at: null,
    rationale: null,
    recommended_revision: null,
    ...over,
  };
}

/** A subject with nothing marked: no band, no grades, no direction. */
function unmeasured(over: Partial<SubjectReadiness> = {}): SubjectReadiness {
  return subject({
    score: null,
    predicted_grade: null,
    status: null,
    averaging_score: null,
    averaging_grade: null,
    marked_piece_count: 0,
    direction: null,
    ...over,
  });
}

function stubFetch(subjects: SubjectReadiness[], narrative: string | null = null) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200 });
      if (url.includes("/me/children")) return json([{ id: 2, name: "Sara", role: "student" }]);
      if (url.includes("/narrative")) {
        return json({ text: narrative, generated_at: null, prompt_version: null });
      }
      if (url.includes("/readiness/students/")) {
        return json({ student_id: 2, student_name: "Sara", subjects });
      }
      return json([]);
    }),
  );
}

function renderParent() {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter>
        <ParentDashboard />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

test("a child with no marked work still renders a complete screen", async () => {
  // `not enough data yet` is a first-class state here: a newly linked parent
  // sees mostly this, and it has to look deliberate rather than broken.
  stubFetch([unmeasured(), unmeasured({ subject_id: 2, subject_name: "Biology" })]);
  const { container } = renderParent();

  expect(
    await screen.findByText("There isn't enough marked work yet to say how Sara is doing."),
  ).toBeInTheDocument();
  expect(screen.getByText("No marked work yet")).toBeInTheDocument();
  expect(screen.getAllByText("not enough data yet")).toHaveLength(2);
  // No zero, no empty bar, no empty panel.
  expect(container.textContent).not.toMatch(/\b0%/);
  expect(screen.getByText("What you can do")).toBeInTheDocument();
});

test("WHAT YOU CAN DO is present in every state", async () => {
  for (const subjects of [[], [unmeasured()], [subject()], [subject({ status: "at_risk" })]]) {
    expect(whatYouCanDo(subjects)).toBeTruthy();
    expect(whatYouCanDo(subjects)).toMatch(/\.$/);
  }

  stubFetch([subject()]);
  renderParent();
  expect(
    await screen.findByText("Nothing is needed right now. We'll tell you if that changes."),
  ).toBeInTheDocument();
});

test("no gendered pronoun appears in the rendered copy", async () => {
  // No gender is stored on User, and inferring one from a name misgenders real
  // people. The design spec's own §6 mock uses "her"; the copy rule governs.
  stubFetch(
    [subject(), subject({ subject_id: 2, subject_name: "Maths", status: "at_risk" })],
    "Sara's chemistry has moved up steadily this month.",
  );
  const { container } = renderParent();
  await screen.findByText(/Sara is on track/);
  expect(container.textContent).not.toMatch(/\b(he|she|him|her|hers|his)\b/i);
});

test("the narrative section states its absence rather than rendering an empty block", async () => {
  stubFetch([subject()], null);
  renderParent();
  expect(await screen.findByText("How it's going")).toBeInTheDocument();
  // find, not get: the section shows a skeleton until the narrative request
  // has answered, rather than claiming "nothing written" before it knows.
  expect(await screen.findByText(/Nothing written yet/)).toBeInTheDocument();
});

test("a stored narrative is read, never generated here", async () => {
  stubFetch([subject()], "Chemistry has moved up steadily this month.");
  renderParent();
  expect(
    await screen.findByText("Chemistry has moved up steadily this month."),
  ).toBeInTheDocument();
  // No control on this screen writes anything: a parent cannot regenerate,
  // approve or suppress, and is never shown a task.
  expect(
    screen.queryByRole("button", { name: /prepare|generate|approve/i }),
  ).not.toBeInTheDocument();
});

test("predicted and averaging are both shown and distinguished", async () => {
  stubFetch([subject()]);
  const { container } = renderParent();
  await screen.findByText("Chemistry");
  // Each grade says which grade it is — "predicted 7 · averaging 6" left a
  // parent to guess what "averaging" meant.
  expect(container.textContent).toContain("Predicted grade 7 · Averaging grade 6 in marked work");
});

test("no per-homework detail reaches the parent screen", async () => {
  // Per-piece results turn this into a surveillance surface the student can
  // feel. Aggregates and direction only.
  stubFetch([subject()]);
  const { container } = renderParent();
  await screen.findByText("Chemistry");
  expect(container.textContent).not.toMatch(/\d+\s*\/\s*\d+/);
  expect(screen.queryByText(/homework/i)).not.toBeInTheDocument();
});

const biology = (over: Partial<SubjectReadiness> = {}) =>
  subject({ subject_id: 2, subject_name: "Biology", ...over });
const physics = (over: Partial<SubjectReadiness> = {}) =>
  subject({ subject_id: 3, subject_name: "Physics", ...over });

test.each([
  // One or two measured subjects are named rather than counted: the counting
  // template produced "needs support in one of one subjects".
  [[subject()], "Sara is on track in Chemistry."],
  [[subject({ status: "at_risk" })], "Sara needs support in Chemistry."],
  [[subject(), biology()], "Sara is on track in Chemistry and Biology."],
  [
    [subject(), biology({ status: "at_risk" })],
    "Sara is on track in Chemistry but needs support in Biology.",
  ],
  [
    [subject({ status: "at_risk" }), biology({ status: "needs_attention" })],
    "Sara needs support in Chemistry and Biology.",
  ],
  // From three up the count reads naturally.
  [[subject(), biology(), physics()], "Sara is on track in all three subjects."],
  [
    [subject(), biology({ status: "at_risk" }), physics()],
    "Sara is on track in two of three subjects.",
  ],
  [
    [
      subject({ status: "at_risk" }),
      biology({ status: "at_risk" }),
      physics({ status: "at_risk" }),
    ],
    "Sara needs support in all three subjects.",
  ],
  [[unmeasured()], "There isn't enough marked work yet to say how Sara is doing."],
])("the verdict states the child's position", (subjects, expected) => {
  expect(parentVerdict("Sara", subjects)).toBe(expected);
});

test("an unmeasured subject is neither on track nor in trouble", () => {
  // Counting it either way would be a claim. Two banded subjects, one not.
  expect(parentVerdict("Sara", [subject(), biology(), unmeasured({ subject_id: 4 })])).toBe(
    "Sara is on track in Chemistry and Biology.",
  );
  // And a count says what it counted when an unmeasured subject is beside it.
  expect(
    parentVerdict("Sara", [subject(), biology(), physics(), unmeasured({ subject_id: 4 })]),
  ).toBe("Sara is on track in all three subjects with marked work.");
});

test("no verdict counts a single subject as a fraction of one", () => {
  for (const status of ["on_track", "needs_attention", "at_risk"] as const) {
    expect(parentVerdict("Sara", [subject({ status })])).not.toMatch(/of one|all one|one of/);
  }
});
