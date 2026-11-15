import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import TeachingPlanView from "../tutor/TeachingPlanView";

const zone = vi.hoisted(() => ({ value: null as string | null }));
vi.mock("../auth/AuthContext", () => ({ useMyTimezone: () => zone.value }));

/* T-078 review round: the plan opens on this week and the next three, one line per lesson,
   one notice region. "Today" is fixed so the folds are deterministic. */

const CHAPTERS = [{ id: 1, code: "C1", title: "Atoms", position: 1 }];

const slot = (id: number, date: string, over: Record<string, unknown> = {}) => ({
  id,
  chapter_id: 1,
  chapter_code: "C1",
  chapter_title: "Atoms",
  scheduled_date: date,
  sequence: id,
  provenance: "generated",
  cancelled: false,
  start_time: null,
  lesson_id: null,
  lesson_origin: null,
  ...over,
});

const plan = (slots: unknown[], over: Record<string, unknown> = {}) => ({
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
  accepted_at: "2027-01-02T10:00:00Z",
  ...over,
});

const BEHIND = {
  planned_to_date: 5,
  taught_to_date: 3,
  missed: 2,
  earliest_missed_date: "2027-01-05",
  earliest_missed_chapter: { id: 1, code: "C1", title: "Atoms" },
};

function stub(
  overview: Record<string, unknown>,
  opts: { cancelUnshifted?: boolean; failDraft?: boolean } = {},
) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), "http://localhost");
      const method = (init?.method ?? "GET").toUpperCase();
      const json = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status });
      if (url.pathname.endsWith("/chapters")) return json(CHAPTERS);
      if (method === "POST" && url.pathname.endsWith("/draft") && opts.failDraft)
        return json({ detail: "The draft service is down." }, 500);
      if (method === "POST" && url.pathname.endsWith("/cancel") && opts.cancelUnshifted)
        return json({
          plan: {
            draft: null,
            accepted: null,
            timetable_defaults: { lessons_per_week: null, lesson_minutes: null },
            ...overview,
          },
          shifted: false,
          message: "That lesson could not be rescheduled.",
        });
      if (method === "PATCH")
        return json(slot(1, "2027-01-15", { provenance: "manually_modified" }));
      return json({
        draft: null,
        accepted: null,
        timetable_defaults: { lessons_per_week: null, lesson_minutes: null },
        ...overview,
      });
    }),
  );
}

function renderView() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <TeachingPlanView groupId={5} subjectId={3} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  // Only the clock: timers stay real so queries and waitFor keep working.
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2027-01-13T09:00:00Z")); // a Wednesday
  zone.value = null;
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

const WEEKS = [
  slot(1, "2026-12-28"),
  slot(2, "2027-01-04"),
  slot(3, "2027-01-11"),
  slot(4, "2027-01-18"),
  slot(5, "2027-01-25"),
  slot(6, "2027-02-01"),
  slot(7, "2027-02-08"),
  slot(8, "2027-02-15"),
];

test("hand-edited and cancelled are visible plain words; Recorded from the plan stays for screen readers", async () => {
  stub({
    accepted: plan([
      slot(1, "2027-01-11", { provenance: "manually_modified" }),
      slot(2, "2027-01-14", { cancelled: true }),
      slot(3, "2027-01-15", { provenance: "confirmed", lesson_id: 4, lesson_origin: "plan" }),
    ]),
  });
  renderView();
  await screen.findByText("Week of 11 Jan 2027");
  expect(screen.getByText("hand-edited")).not.toHaveClass("sr-only");
  expect(screen.getByText("hand-edited")).toHaveClass("text-xs", "text-ink-500");
  expect(screen.getByText("cancelled")).not.toHaveClass("sr-only");
  const recorded = screen.getByText(/Recorded from the plan/);
  expect(recorded).toHaveClass("sr-only");
  // Words do not run together in the row's text.
  expect(recorded.textContent).toMatch(/^[ ,]/);
});

test("a plan wholly in the past still opens on its last week", async () => {
  stub({ accepted: plan([slot(1, "2026-11-02"), slot(2, "2026-11-09")]) });
  renderView();
  expect(await screen.findByText("Week of 9 Nov 2026")).toBeInTheDocument();
  expect(screen.getByText("Earlier: 1 week")).toBeInTheDocument();
  expect(screen.queryByText("Week of 2 Nov 2026")).toBeNull();
});

test("the draft's note stays in the draft section and the cancel note shows with it", async () => {
  stub(
    {
      accepted: plan([slot(1, "2027-01-14")]),
      draft: plan([slot(2, "2027-01-18")], { accepted_at: null, draft_job_failed: true }),
    },
    { cancelUnshifted: true },
  );
  renderView();
  const note = await screen.findByText(/did not run/);
  const draftHeading = screen.getByText("Proposed changes");
  expect(draftHeading.parentElement).toContainElement(note);
  fireEvent.click(await screen.findByRole("button", { name: /^Cancel lesson, 14 Jan 2027/ }));
  expect(await screen.findByText("That lesson could not be rescheduled.")).toBeInTheDocument();
  expect(screen.getByText(/did not run/)).toBeInTheDocument();
});

test("Re-plan stays reachable while the draft has a note, and while a notice shows", async () => {
  stub(
    {
      accepted: plan([slot(1, "2027-01-14")]),
      draft: plan([slot(2, "2027-01-18")], { accepted_at: null, draft_job_failed: true }),
      progress: BEHIND,
    },
    { cancelUnshifted: true },
  );
  renderView();
  expect(await screen.findByRole("button", { name: "Re-plan" })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /^Cancel lesson, 14 Jan 2027/ }));
  expect(await screen.findByText("That lesson could not be rescheduled.")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Re-plan" })).toBeInTheDocument();
});

test("the notice region is mounted before there is anything to say", async () => {
  stub({ accepted: plan([slot(1, "2027-01-14")]) });
  renderView();
  await screen.findByText("Week of 11 Jan 2027");
  expect(screen.getAllByRole("status").some((el) => el.textContent === "")).toBe(true);
});

test("row actions are not hidden for a touch laptop: hiding is only for a fine hovering pointer", async () => {
  stub({ accepted: plan([slot(1, "2027-01-14")]) });
  renderView();
  await screen.findByText("Week of 11 Jan 2027");
  const edit = screen.getByRole("button", { name: /^Edit, 14 Jan 2027/ });
  const group = edit.parentElement as HTMLElement;
  expect(group.className).not.toMatch(/(^|\s)md:opacity-0/);
  expect(group.className).toContain(
    "[@media(hover:hover)_and_(pointer:fine)_and_(not_(any-pointer:coarse))]:opacity-0",
  );
  // "..." comes first in the DOM, owns an id'd target, and is a phone-sized target.
  const more = screen.getByRole("button", { name: /^More actions/ });
  expect(more.compareDocumentPosition(edit) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(more.getAttribute("aria-controls")).toBe(group.id);
  expect(group.id).not.toBe("");
  expect(more.className).toContain("max-md:min-h-11");
  expect(edit.className).toContain("max-md:min-h-11");
});

test("the actions close after one is used", async () => {
  stub({ accepted: plan([slot(1, "2027-01-14")]) });
  renderView();
  await screen.findByText("Week of 11 Jan 2027");
  const more = screen.getByRole("button", { name: /^More actions/ });
  fireEvent.click(more);
  expect(more).toHaveAttribute("aria-expanded", "true");
  fireEvent.click(screen.getByRole("button", { name: /^Edit, 14 Jan 2027/ }));
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  expect(screen.getByRole("button", { name: /^More actions/ })).toHaveAttribute(
    "aria-expanded",
    "false",
  );
});

test("action names contain their visible text and tell rows on one date apart", async () => {
  stub({
    accepted: plan([
      slot(1, "2027-01-14", { start_time: "09:00:00" }),
      slot(2, "2027-01-14", { start_time: "15:30:00" }),
    ]),
  });
  renderView();
  await screen.findByText("Week of 11 Jan 2027");
  expect(
    screen.getByRole("button", { name: "Cancel lesson, 14 Jan 2027 at 09:00, C1 Atoms" }),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Edit, 14 Jan 2027 at 15:30, C1 Atoms" }),
  ).toBeInTheDocument();
});

test("editing focuses the date, and Cancel or Save returns focus to the row's Edit button", async () => {
  stub({ accepted: plan([slot(1, "2027-01-14")]) });
  renderView();
  await screen.findByText("Week of 11 Jan 2027");
  fireEvent.click(screen.getByRole("button", { name: /^Edit, 14 Jan 2027/ }));
  expect(screen.getByLabelText("Lesson date")).toHaveFocus();
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  await waitFor(() =>
    expect(screen.getByRole("button", { name: /^Edit, 14 Jan 2027/ })).toHaveFocus(),
  );
  fireEvent.click(screen.getByRole("button", { name: /^Edit, 14 Jan 2027/ }));
  fireEvent.change(screen.getByLabelText("Lesson date"), { target: { value: "2027-01-15" } });
  fireEvent.click(screen.getByRole("button", { name: "Save lesson" }));
  await waitFor(() => expect(screen.queryByLabelText("Lesson date")).toBeNull());
  await waitFor(() =>
    expect(screen.getByRole("button", { name: /^Edit, 14 Jan 2027/ })).toHaveFocus(),
  );
});

test("fold summaries say how many weeks", async () => {
  stub({ accepted: plan(WEEKS) });
  renderView();
  expect(await screen.findByText("Earlier: 2 weeks")).toBeInTheDocument();
});

test("'today' for the fold is the tutor's own zone, not the browser's", async () => {
  // Sunday 17 Jan 12:00 UTC is already Monday 18 Jan in Kiritimati (UTC+14).
  vi.setSystemTime(new Date("2027-01-17T12:00:00Z"));
  zone.value = "Pacific/Kiritimati";
  stub({ accepted: plan(WEEKS) });
  renderView();
  expect(await screen.findByText("Week of 18 Jan 2027")).toBeInTheDocument();
  expect(screen.queryByText("Week of 11 Jan 2027")).toBeNull();
  expect(screen.getByText("Earlier: 3 weeks")).toBeInTheDocument();
});
