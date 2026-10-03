import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, test, vi } from "vitest";
import TeachingPlanView from "../tutor/TeachingPlanView";

/* Task 6.6: the behind-schedule banner and its one-click re-plan, and the
   syllabus-change reflow notice (owed by 6.8). */

const CHAPTERS = [{ id: 1, code: "C1", title: "Atoms", position: 1 }];

const slot = (id: number, date: string) => ({
  id,
  chapter_id: 1,
  chapter_code: "C1",
  chapter_title: "Atoms",
  scheduled_date: date,
  sequence: id,
  provenance: "generated",
});

const outcome = (reflow: Record<string, unknown> | null = null) => ({
  status: "drafted",
  drafted_at: "2026-09-01T09:00:00Z",
  weight_source: "ai",
  degraded_reason: null,
  guidance_used: false,
  guidance_note: null,
  defaulted_chapters: 0,
  chapters: [],
  failure_code: null,
  failure_message: null,
  reflow,
});

function plan(over: Record<string, unknown> = {}) {
  return {
    id: 1,
    exam_date: "2027-05-10",
    lessons_per_week: 2,
    lesson_minutes: 60,
    past_paper_start_date: null,
    breaks: [],
    slots: [slot(1, "2027-01-04")],
    outcome: outcome(),
    drafting: false,
    draft_job_failed: false,
    accepted_at: "2026-09-01T09:00:00Z",
    ...over,
  };
}

const progress = (missed: number) => ({
  planned_to_date: 5,
  taught_to_date: 5 - missed,
  missed,
  earliest_missed_date: missed ? "2026-10-06" : null,
  earliest_missed_chapter: missed ? { id: 1, code: "C1", title: "Atoms" } : null,
});

function stub(
  overview: Record<string, unknown>,
  replanned?: Record<string, unknown>,
  gate?: Promise<void>,
) {
  const calls: { method: string; url: string }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), "http://localhost");
      const method = (init?.method ?? "GET").toUpperCase();
      calls.push({ method, url: url.pathname });
      const json = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status });
      if (url.pathname.endsWith("/chapters")) return json(CHAPTERS);
      if (method === "POST" && url.pathname.endsWith("/replan")) {
        await gate;
        return json({ ...overview, ...replanned }, 202);
      }
      return json({
        draft: null,
        accepted: null,
        timetable_defaults: { lessons_per_week: null, lesson_minutes: null },
        progress: null,
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

test("a class with unrecorded lessons gets a plain banner and a Re-plan button", async () => {
  const calls = stub(
    { accepted: plan(), progress: progress(3) },
    { draft: plan({ id: 2, accepted_at: null, drafting: true, outcome: null, slots: [] }) },
  );
  renderView();
  const banner = await screen.findByText(/3 planned lessons haven't been recorded since/);
  expect(banner).toHaveTextContent("Tue 6 Oct");
  expect(banner).toHaveTextContent("record them, or re-plan from today");
  expect(banner.textContent).not.toMatch(/missed|behind|late/i);

  fireEvent.click(screen.getByRole("button", { name: "Re-plan" }));
  await waitFor(() =>
    expect(calls.some((c) => c.method === "POST" && c.url === "/api/v1/groups/5/plan/replan")).toBe(
      true,
    ),
  );
  // It only drafts: the tutor still has to accept, and nothing was accepted here.
  expect(calls.some((c) => c.url.endsWith("/accept"))).toBe(false);
  // The view now says the draft is being made.
  expect(await screen.findByRole("button", { name: /Drafting/ })).toBeDisabled();
});

test("a plan with no progress block shows no banner", async () => {
  stub({ accepted: plan(), progress: null });
  renderView();
  await screen.findByText("Live plan");
  expect(screen.queryByText(/haven't been recorded/)).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Re-plan" })).not.toBeInTheDocument();
});

test("no gap, no banner; no accepted plan, no banner", async () => {
  stub({ accepted: plan(), progress: progress(0) });
  renderView();
  await screen.findByText("Live plan");
  expect(screen.queryByRole("button", { name: "Re-plan" })).not.toBeInTheDocument();
});

test("one lesson reads in the singular", async () => {
  stub({ accepted: plan(), progress: progress(1) });
  renderView();
  expect(await screen.findByText(/1 planned lesson hasn't been recorded/)).toBeInTheDocument();
});

test("re-planning over an existing draft asks first", async () => {
  const calls = stub({
    accepted: plan(),
    draft: plan({ id: 2, accepted_at: null }),
    progress: progress(2),
  });
  renderView();
  fireEvent.click(await screen.findByRole("button", { name: "Re-plan" }));
  expect(await screen.findByText("Re-plan from today?")).toBeInTheDocument();
  expect(calls.some((c) => c.url.endsWith("/replan"))).toBe(false);
});

test("re-planning over a draft with only inputs still asks first", async () => {
  const calls = stub({
    accepted: plan(),
    draft: plan({ id: 2, accepted_at: null, slots: [], outcome: null }),
    progress: progress(2),
  });
  renderView();
  fireEvent.click(await screen.findByRole("button", { name: "Re-plan" }));
  expect(await screen.findByText("Re-plan from today?")).toBeInTheDocument();
  expect(calls.some((c) => c.url.endsWith("/replan"))).toBe(false);
});

test("while the re-plan request is out the draft button is disabled too", async () => {
  let release: () => void = () => {};
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  // A draft exists and is idle, so only the pending re-plan can disable the button.
  stub(
    { accepted: plan(), draft: plan({ id: 2, accepted_at: null }), progress: progress(2) },
    { draft: plan({ id: 2, accepted_at: null, drafting: true }) },
    gate,
  );
  renderView();
  const draftButton = await screen.findByRole("button", { name: "Draft a new plan" });
  await waitFor(() => expect(draftButton).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "Re-plan" }));
  const buttons = await screen.findAllByRole("button", { name: "Re-plan" });
  fireEvent.click(buttons[buttons.length - 1]); // the dialog's confirm
  // The request is still out: the draft button is already disabled.
  await waitFor(() => expect(screen.getByRole("button", { name: /Drafting/ })).toBeDisabled());
  release();
  expect(await screen.findByRole("button", { name: /Drafting/ })).toBeDisabled();
});

test("a failed reflow says so, with the reason", async () => {
  stub({
    accepted: plan({
      outcome: outcome({
        status: "failed",
        at: "2026-10-01T12:00:00Z",
        reason: null,
        failure_message: "Only 2 lessons fit before the exam.",
        last_success_at: null,
      }),
    }),
  });
  renderView();
  const note = await screen.findByText(/couldn't be reshuffled/);
  expect(note).toHaveTextContent("Your syllabus changed on");
  expect(note).toHaveTextContent("Only 2 lessons fit before the exam.");
  expect(screen.getByRole("alert")).toBe(note);
});

test("a skipped reflow is quiet and a successful one is a subtle note", async () => {
  stub({
    accepted: plan({
      outcome: outcome({ status: "skipped", at: "2026-10-01T12:00:00Z", reason: "no schedule" }),
    }),
    draft: plan({
      id: 2,
      accepted_at: null,
      outcome: outcome({ status: "reflowed", at: "2026-10-02T12:00:00Z" }),
    }),
  });
  renderView();
  expect(
    await screen.findByText(/the plan was left as it was \(no schedule\)/),
  ).toBeInTheDocument();
  expect(screen.getByText(/Updated for your syllabus changes on/)).toBeInTheDocument();
  // Neither is an alert.
  expect(screen.queryByText(/couldn't be reshuffled/)).not.toBeInTheDocument();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

test("an unknown reflow status renders nothing", async () => {
  stub({
    accepted: plan({ outcome: outcome({ status: "mystery", at: "2026-10-01T12:00:00Z" }) }),
  });
  renderView();
  await screen.findByText("Live plan");
  expect(screen.queryByText(/syllabus/)).not.toBeInTheDocument();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});
