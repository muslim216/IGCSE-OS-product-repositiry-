import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, test, vi } from "vitest";
import TeachingPlanView from "../tutor/TeachingPlanView";

/* Task 6.4 review: the draft/poll/accept flow and the outcome notes. */

const CHAPTERS = [{ id: 1, code: "C1", title: "Atoms", position: 1 }];

const slot = {
  id: 1,
  chapter_id: 1,
  chapter_code: "C1",
  chapter_title: "Atoms",
  scheduled_date: "2027-01-04",
  sequence: 1,
  provenance: "generated",
};

const OUTCOME = {
  status: "drafted",
  drafted_at: "2027-01-04T09:00:00Z",
  weight_source: "ai",
  degraded_reason: null,
  guidance_used: false,
  guidance_note: null,
  defaulted_chapters: 0,
  chapters: [],
  failure_code: null,
  failure_message: null,
};

const plan = (over: Record<string, unknown> = {}) => ({
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
});

const wrap = (draft: unknown, accepted: unknown = null) => ({
  draft,
  accepted,
  timetable_defaults: { lessons_per_week: null, lesson_minutes: null },
});

type Respond = (method: string, path: string) => { body: unknown; status?: number };

function stub(respond: Respond) {
  const calls: { method: string; path: string }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), "http://localhost");
      const method = (init?.method ?? "GET").toUpperCase();
      calls.push({ method, path: url.pathname });
      if (url.pathname.endsWith("/chapters"))
        return new Response(JSON.stringify(CHAPTERS), { status: 200 });
      const { body, status = 200 } = respond(method, url.pathname);
      return new Response(JSON.stringify(body), { status });
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

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

test("after the draft POST the button reads Drafting, polls, and stops when the job ends", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  let jobDone = false;
  const calls = stub((method, path) => {
    if (method === "POST" && path.endsWith("/draft"))
      return { body: wrap(plan({ drafting: true })), status: 202 };
    return {
      body: wrap(
        jobDone
          ? plan({ slots: [slot], outcome: OUTCOME })
          : plan({ drafting: calls.some((c) => c.method === "POST") }),
      ),
    };
  });
  renderView();
  const button = await screen.findByRole("button", { name: "Draft my plan" });
  await waitFor(() => expect(button).toBeEnabled());
  fireEvent.click(button);
  expect(await screen.findByRole("button", { name: /Drafting/ })).toBeDisabled();

  const gets = () => calls.filter((c) => c.method === "GET" && c.path.endsWith("/plan")).length;
  const before = gets();
  await act(async () => {
    await vi.advanceTimersByTimeAsync(3100);
  });
  expect(gets()).toBeGreaterThan(before);

  jobDone = true;
  await act(async () => {
    await vi.advanceTimersByTimeAsync(3100);
  });
  expect(await screen.findByRole("button", { name: "Draft my plan" })).toBeEnabled();
  const settled = gets();
  await act(async () => {
    await vi.advanceTimersByTimeAsync(10000);
  });
  expect(gets()).toBe(settled);
});

test("accepting moves the plan to Live plan", async () => {
  let accepted = false;
  stub((method, path) => {
    if (method === "POST" && path.endsWith("/accept")) {
      accepted = true;
      return {
        body: wrap(null, plan({ slots: [slot], accepted_at: "2027-01-02T10:00:00Z" })),
      };
    }
    return {
      body: accepted
        ? wrap(null, plan({ slots: [slot], accepted_at: "2027-01-02T10:00:00Z" }))
        : wrap(plan({ slots: [slot], outcome: OUTCOME })),
    };
  });
  renderView();
  fireEvent.click(await screen.findByRole("button", { name: "Accept plan" }));
  const dialog = await screen.findByRole("dialog");
  fireEvent.click(within(dialog).getByRole("button", { name: "Accept plan" }));
  expect(await screen.findByText("Live plan")).toBeInTheDocument();
  expect(screen.queryByText("Draft plan")).not.toBeInTheDocument();
});

test("a 409 on accept shows the server's message", async () => {
  stub((method, path) =>
    method === "POST" && path.endsWith("/accept")
      ? { body: { detail: "The draft has no lessons yet." }, status: 409 }
      : { body: wrap(plan({ slots: [slot], outcome: OUTCOME })) },
  );
  renderView();
  fireEvent.click(await screen.findByRole("button", { name: "Accept plan" }));
  const dialog = await screen.findByRole("dialog");
  fireEvent.click(within(dialog).getByRole("button", { name: "Accept plan" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("The draft has no lessons yet.");
});

test("a stale draft says inputs changed and cannot be accepted", async () => {
  stub(() => ({ body: wrap(plan({ slots: [slot], outcome: { ...OUTCOME, status: "stale" } })) }));
  renderView();
  expect(await screen.findByText(/Inputs changed since this draft/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Accept plan" })).toBeDisabled();
});

test("a skipped draft explains why Accept is unavailable", async () => {
  stub(() => ({ body: wrap(plan({ slots: [slot], outcome: { ...OUTCOME, status: "skipped" } })) }));
  renderView();
  expect(await screen.findByText(/nothing to accept/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Accept plan" })).toBeDisabled();
});

test("AI weights with defaulted chapters warn and mark the rows", async () => {
  stub(() => ({
    body: wrap(
      plan({
        slots: [slot],
        outcome: {
          ...OUTCOME,
          defaulted_chapters: 1,
          chapters: [
            { chapter_id: 1, chapter_code: "C1", chapter_title: "Atoms", weight: 1, reason: null },
          ],
        },
      }),
    ),
  }));
  renderView();
  expect(await screen.findByText(/1 chapter got a default share/)).toBeInTheDocument();
  expect(screen.getByText("default share")).toBeInTheDocument();
});

test("a failed chapter list is reported with a retry beside the chapter select", async () => {
  let chaptersCalls = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), "http://localhost");
      if (url.pathname.endsWith("/chapters")) {
        chaptersCalls += 1;
        // Fails once, then the retry succeeds.
        return chaptersCalls === 1
          ? new Response(JSON.stringify({ detail: "boom" }), { status: 500 })
          : new Response(JSON.stringify(CHAPTERS), { status: 200 });
      }
      return new Response(JSON.stringify(wrap(plan({ slots: [slot], outcome: OUTCOME }))), {
        status: 200,
      });
    }),
  );
  renderView();
  fireEvent.click(await screen.findByRole("button", { name: "Edit the 4 Jan 2027 lesson" }));
  expect(await screen.findByText(/chapter list didn't load/)).toBeInTheDocument();
  expect(screen.getByLabelText("Lesson chapter")).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Retry" }));
  await waitFor(() => expect(screen.getByLabelText("Lesson chapter")).toBeEnabled());
  expect(screen.queryByText(/chapter list didn't load/)).not.toBeInTheDocument();
  expect(chaptersCalls).toBe(2);
});

test("Edit is disabled on proposed slots while a draft job runs", async () => {
  stub(() => ({ body: wrap(plan({ drafting: true, slots: [slot], outcome: OUTCOME })) }));
  renderView();
  expect(await screen.findByRole("button", { name: "Edit the 4 Jan 2027 lesson" })).toBeDisabled();
});
