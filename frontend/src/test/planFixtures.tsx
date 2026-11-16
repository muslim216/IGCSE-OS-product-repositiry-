import { render } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, vi } from "vitest";
import TeachingPlanView from "../tutor/TeachingPlanView";

/* Shared by the teaching-plan view tests, so the plan, slot and server fixtures
   live in one place instead of being copied into each file. */

export const CHAPTERS = [{ id: 1, code: "C1", title: "Atoms", position: 1 }];

export type Slot = Record<string, unknown> & {
  id: number;
  scheduled_date: string;
  cancelled: boolean;
};

export const slot = (id: number, date: string, over: Record<string, unknown> = {}): Slot => ({
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

export const plan = (slots: unknown[], over: Record<string, unknown> = {}) => ({
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

export const BEHIND = {
  planned_to_date: 5,
  taught_to_date: 3,
  missed: 2,
  earliest_missed_date: "2027-01-05",
  earliest_missed_chapter: { id: 1, code: "C1", title: "Atoms" },
};

/** Eight weekly lessons, two before "today" and five after, so the folds exist. */
export const WEEKS = [
  slot(1, "2026-12-28"),
  slot(2, "2027-01-04"),
  slot(3, "2027-01-11"),
  slot(4, "2027-01-18"),
  slot(5, "2027-01-25"),
  slot(6, "2027-02-01"),
  slot(7, "2027-02-08"),
  slot(8, "2027-02-15"),
];

/** The plan overview with the fields a test does not care about filled in. */
export const overviewWith = (over: Record<string, unknown>) => ({
  draft: null,
  accepted: null,
  timetable_defaults: { lessons_per_week: null, lesson_minutes: null },
  ...over,
});

export type PlanRequest = {
  url: URL;
  method: string;
  init?: RequestInit;
  json: (body: unknown, status?: number) => Response;
};

/** A fake server for the plan screen. `extra` answers the calls a test cares
 *  about and returns nothing for the rest, which get the chapters or the overview. */
export function stubPlanApi(
  overview: () => unknown,
  extra: (req: PlanRequest) => Response | undefined = () => undefined,
) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), "http://localhost");
      const method = (init?.method ?? "GET").toUpperCase();
      const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
      if (url.pathname.endsWith("/chapters")) return json(CHAPTERS);
      return extra({ url, method, init, json }) ?? json(overview());
    }),
  );
}

export function renderView() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <TeachingPlanView groupId={5} subjectId={3} />
    </QueryClientProvider>,
  );
}

/** Pins "today" to a Wednesday. Only the clock is faked: timers stay real so
 *  queries and waitFor keep working. */
export function pinTodayToWednesday(after?: () => void) {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2027-01-13T09:00:00Z"));
    after?.();
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });
}
