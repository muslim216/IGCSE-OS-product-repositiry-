import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, test, vi } from "vitest";
import TeachingPlanView from "../tutor/TeachingPlanView";

/* Task 7.4 (AV-119, AV-120): start times, cancelled lessons, "Recorded from the plan". */

const CHAPTERS = [{ id: 1, code: "C1", title: "Atoms", position: 1 }];

const slot = (id: number, date: string, over: Record<string, unknown> = {}) => ({
  id,
  chapter_id: 1,
  chapter_code: "C1",
  chapter_title: "Atoms",
  scheduled_date: date,
  sequence: id,
  provenance: "generated",
  start_time: "17:00:00",
  cancelled: false,
  lesson_id: null,
  lesson_origin: null,
  ...over,
});

const accepted = (slots: unknown[]) => ({
  id: 1,
  exam_date: "2027-05-10",
  lessons_per_week: 2,
  lesson_minutes: 60,
  past_paper_start_date: null,
  breaks: [],
  slots,
  outcome: null,
  drafting: false,
  draft_job_failed: false,
  accepted_at: "2027-01-01T09:00:00Z",
});

function stub(slots: unknown[], cancelResult?: Record<string, unknown>) {
  const calls: { method: string; url: string; body?: Record<string, unknown> }[] = [];
  const overview = (s: unknown[]) => ({
    draft: null,
    accepted: accepted(s),
    timetable_defaults: { lessons_per_week: 2, lesson_minutes: 60 },
    progress: null,
  });
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), "http://localhost");
      const method = (init?.method ?? "GET").toUpperCase();
      const body = init?.body ? JSON.parse(String(init.body)) : undefined;
      calls.push({ method, url: url.pathname, body });
      const json = (b: unknown) => new Response(JSON.stringify(b), { status: 200 });
      if (url.pathname.endsWith("/chapters")) return json(CHAPTERS);
      if (url.pathname.endsWith("/cancel"))
        return json({
          shifted: true,
          moved: 1,
          message: null,
          ...cancelResult,
          plan: overview(slots),
        });
      if (method === "PATCH") return json(slot(10, "2027-02-01"));
      return json(overview(slots));
    }),
  );
  return calls;
}

function renderView() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <TeachingPlanView groupId={5} subjectId={3} />
    </QueryClientProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

test("each lesson shows its own start time, and none when it has none (never midnight)", async () => {
  stub([slot(1, "2027-02-01"), slot(2, "2027-02-04", { start_time: null })]);
  renderView();
  expect(await screen.findByText(/1 Feb 2027 · 17:00/)).toBeInTheDocument();
  expect(screen.getByText("4 Feb 2027")).toBeInTheDocument();
  expect(screen.queryByText(/00:00/)).not.toBeInTheDocument();
});

test("a cancelled lesson is shown as cancelled and offers no actions", async () => {
  stub([slot(1, "2027-02-01", { cancelled: true }), slot(2, "2027-02-04")]);
  renderView();
  expect(await screen.findByText("cancelled")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Cancel the 1 Feb 2027 lesson/ })).toBeNull();
  expect(screen.queryByRole("button", { name: /Edit the 1 Feb 2027 lesson/ })).toBeNull();
  expect(screen.getByRole("button", { name: /Edit the 4 Feb 2027 lesson/ })).toBeInTheDocument();
});

test("an auto-recorded lesson says it was recorded from the plan; a tutor's does not", async () => {
  stub([
    slot(1, "2027-02-01", { provenance: "confirmed", lesson_id: 4, lesson_origin: "plan" }),
    slot(2, "2027-02-04", { provenance: "confirmed", lesson_id: 5, lesson_origin: "tutor" }),
  ]);
  renderView();
  expect(await screen.findAllByText("Recorded from the plan")).toHaveLength(1);
  expect(screen.getAllByText("taught")).toHaveLength(2);
  // A taught lesson cannot be cancelled here.
  expect(screen.queryByRole("button", { name: /Cancel the/ })).toBeNull();
});

test("Cancel lesson posts to the slot's cancel endpoint", async () => {
  const calls = stub([slot(1, "2027-02-01")]);
  renderView();
  fireEvent.click(await screen.findByRole("button", { name: "Cancel the 1 Feb 2027 lesson" }));
  await waitFor(() =>
    expect(calls.some((c) => c.method === "POST" && c.url.endsWith("/plan/slots/1/cancel"))).toBe(
      true,
    ),
  );
});

test("when there is no room the plan says so", async () => {
  stub([slot(1, "2027-02-01")], {
    shifted: false,
    moved: 0,
    message: "No room before the exam — re-plan to catch up",
  });
  renderView();
  fireEvent.click(await screen.findByRole("button", { name: "Cancel the 1 Feb 2027 lesson" }));
  expect(await screen.findByText(/No room before the exam/)).toBeInTheDocument();
});

test("the start time can be edited per lesson", async () => {
  const calls = stub([slot(1, "2027-02-01")]);
  renderView();
  fireEvent.click(await screen.findByRole("button", { name: "Edit the 1 Feb 2027 lesson" }));
  fireEvent.change(screen.getByLabelText("Lesson start time"), { target: { value: "18:30" } });
  fireEvent.click(screen.getByRole("button", { name: "Save lesson" }));
  await waitFor(() =>
    expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({ start_time: "18:30" }),
  );
});
