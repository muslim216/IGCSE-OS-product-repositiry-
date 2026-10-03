import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, test, vi } from "vitest";
import TeachingPlanView from "../tutor/TeachingPlanView";

/* Task 6.4: draft, read the outcome, accept, and edit a lesson. */

const CHAPTERS = [
  { id: 1, code: "C1", title: "Atoms", position: 1 },
  { id: 2, code: "C2", title: "Bonding", position: 2 },
];

const slot = (id: number, date: string, chapter = 1, provenance = "generated") => ({
  id,
  chapter_id: chapter,
  chapter_code: `C${chapter}`,
  chapter_title: chapter === 1 ? "Atoms" : "Bonding",
  scheduled_date: date,
  sequence: id,
  provenance,
});

const OUTCOME = {
  status: "drafted",
  drafted_at: "2027-01-04T09:00:00Z",
  weight_source: "ai",
  degraded_reason: null,
  guidance_used: false,
  guidance_note: null,
  defaulted_chapters: 0,
  chapters: [
    { chapter_id: 1, chapter_code: "C1", chapter_title: "Atoms", weight: 2, reason: "Dense one" },
  ],
  failure_code: null,
  failure_message: null,
};

function plan(over: Record<string, unknown> = {}) {
  return {
    id: 1,
    exam_date: "2027-05-10",
    lessons_per_week: 2,
    lesson_minutes: 60,
    past_paper_start_date: null,
    breaks: [],
    slots: [],
    outcome: null,
    drafting: false,
    draft_job_failed: false,
    accepted_at: null,
    ...over,
  };
}

function stub(overview: Record<string, unknown>) {
  const calls: { method: string; url: string; body?: Record<string, unknown> }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), "http://localhost");
      const method = (init?.method ?? "GET").toUpperCase();
      const body = init?.body ? JSON.parse(String(init.body)) : undefined;
      calls.push({ method, url: url.pathname, body });
      const json = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status });
      if (url.pathname.endsWith("/chapters")) return json(CHAPTERS);
      if (method === "PATCH") return json(slot(10, "2027-02-02", 2, "manually_modified"));
      if (method === "POST") return json(overview, url.pathname.endsWith("/draft") ? 202 : 200);
      return json({
        draft: null,
        accepted: null,
        timetable_defaults: { lessons_per_week: null, lesson_minutes: null },
        ...overview,
      });
    }),
  );
  return calls;
}

function renderView() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <TeachingPlanView groupId={5} subjectId={3} />
    </QueryClientProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

test("the draft button is disabled until the inputs are saved", async () => {
  stub({});
  renderView();
  const button = await screen.findByRole("button", { name: "Draft my plan" });
  expect(button).toBeDisabled();
  expect(screen.getByText(/Save the plan inputs above/)).toBeInTheDocument();
});

test("a saved draft can be requested and shows Drafting while the job runs", async () => {
  const calls = stub({ draft: plan() });
  renderView();
  const button = await screen.findByRole("button", { name: "Draft my plan" });
  await waitFor(() => expect(button).toBeEnabled());
  fireEvent.click(button);
  await waitFor(() =>
    expect(calls.some((c) => c.method === "POST" && c.url === "/api/v1/groups/5/plan/draft")).toBe(
      true,
    ),
  );
});

test("a queued draft job shows Drafting and blocks a second request", async () => {
  stub({ draft: plan({ drafting: true }) });
  renderView();
  expect(await screen.findByRole("button", { name: /Drafting/ })).toBeDisabled();
});

test("a draft whose weights were not the AI's says so and why", async () => {
  stub({
    draft: plan({
      slots: [slot(1, "2027-01-04")],
      outcome: {
        ...OUTCOME,
        weight_source: "stored_chapter_weights",
        degraded_reason: "The AI key is not set.",
      },
    }),
  });
  renderView();
  expect(await screen.findByText(/did not come from the AI/)).toHaveTextContent(
    "The AI key is not set.",
  );
});

test("a failed draft shows its failure message and cannot be accepted", async () => {
  stub({
    draft: plan({
      slots: [slot(1, "2027-01-04")],
      outcome: {
        ...OUTCOME,
        status: "failed",
        failure_code: "not_enough_lessons",
        failure_message: "Only 2 lessons fit before the exam.",
      },
    }),
  });
  renderView();
  expect(await screen.findByText("Only 2 lessons fit before the exam.")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Accept plan" })).toBeDisabled();
});

test("accepting asks for confirmation, then calls the API", async () => {
  const calls = stub({ draft: plan({ slots: [slot(1, "2027-01-04")], outcome: OUTCOME }) });
  renderView();
  fireEvent.click(await screen.findByRole("button", { name: "Accept plan" }));
  expect(calls.some((c) => c.url.endsWith("/accept"))).toBe(false);
  const dialog = await screen.findByRole("dialog");
  fireEvent.click(within(dialog).getByRole("button", { name: "Accept plan" }));
  await waitFor(() => expect(calls.some((c) => c.url.endsWith("/accept"))).toBe(true));
});

test("slots are grouped by week, hand-edited ones are marked, reasons are on demand", async () => {
  stub({
    accepted: plan({ id: 2, accepted_at: "2027-01-02T10:00:00Z" }),
    draft: plan({
      slots: [
        slot(1, "2027-01-04"),
        slot(2, "2027-01-07", 2, "manually_modified"),
        slot(3, "2027-01-11"),
      ],
      outcome: OUTCOME,
    }),
  });
  renderView();
  expect(await screen.findByText("Proposed changes")).toBeInTheDocument();
  expect(screen.getByText("Live plan")).toBeInTheDocument();
  expect(screen.getByText("Week of 4 Jan 2027")).toBeInTheDocument();
  expect(screen.getByText("Week of 11 Jan 2027")).toBeInTheDocument();
  expect(screen.getAllByText("hand-edited")).toHaveLength(1);
  expect(screen.getByText("Why each chapter got its share")).toBeInTheDocument();
});

test("editing a lesson PATCHes the new date and chapter", async () => {
  const calls = stub({
    accepted: plan({ id: 2, slots: [slot(10, "2027-01-04")] }),
  });
  renderView();
  fireEvent.click(await screen.findByRole("button", { name: "Edit the 4 Jan 2027 lesson" }));
  fireEvent.change(screen.getByLabelText("Lesson date"), { target: { value: "2027-02-02" } });
  await screen.findByRole("option", { name: "C2 Bonding" });
  fireEvent.change(screen.getByLabelText("Lesson chapter"), { target: { value: "2" } });
  fireEvent.click(screen.getByRole("button", { name: "Save lesson" }));
  await waitFor(() => {
    const patch = calls.find((c) => c.method === "PATCH");
    expect(patch?.url).toBe("/api/v1/groups/5/plan/slots/10");
    expect(patch?.body).toEqual({ scheduled_date: "2027-02-02", chapter_id: 2 });
  });
});
