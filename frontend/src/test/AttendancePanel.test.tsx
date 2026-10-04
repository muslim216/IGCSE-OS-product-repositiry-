import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, test, vi } from "vitest";
import AttendancePanel, { NO_ATTENDANCE } from "../components/AttendancePanel";

/* Attendance beside readiness (task 7.2, AV-44). A lesson nobody took
   attendance for is "not taken" and out of the rate; nothing marked means no
   rate at all — never 0% (PROD-2, UX-19). */

const EMPTY = { lessons: 0, present: 0, absent: 0, not_taken: 0, rate: null, classes: [] };

const DATA = {
  lessons: 4,
  present: 2,
  absent: 1,
  not_taken: 1,
  rate: 2 / 3,
  classes: [
    {
      group_id: 1,
      group_name: "Chem Y10",
      lessons: 4,
      present: 2,
      absent: 1,
      not_taken: 1,
      rate: 2 / 3,
      recent: [
        { lesson_id: 4, date: "2026-10-01", start_time: "16:00:00", mode: "online", state: null },
        { lesson_id: 3, date: "2026-09-28", start_time: null, mode: "in_person", state: "absent" },
      ],
    },
  ],
};

function stub(body: unknown) {
  const urls: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      urls.push(new URL(String(input), "http://localhost").pathname);
      return new Response(JSON.stringify(body), { status: 200 });
    }),
  );
  return urls;
}

function renderPanel(props: { studentId: number; own?: boolean }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <AttendancePanel {...props} />
    </QueryClientProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

test("with nothing marked it says so and shows no percentage or bar", async () => {
  stub(EMPTY);
  renderPanel({ studentId: 2 });
  expect(await screen.findByText(NO_ATTENDANCE)).toBeTruthy();
  expect(document.body.textContent).not.toMatch(/%/);
  expect(screen.queryByRole("progressbar")).toBeNull();
});

test("not-taken lessons are stated and kept out of the rate", async () => {
  stub(DATA);
  renderPanel({ studentId: 2 });
  expect(await screen.findByText("Present at 2 of 3 lessons · 1 not taken")).toBeTruthy();
  // A lesson with no mark is "Not taken", never "Absent".
  expect(screen.getByText(/Thu 1 Oct 16:00 · online · Not taken/)).toBeTruthy();
  expect(screen.getByText(/Mon 28 Sep · Absent/)).toBeTruthy();
});

test("a class with only unmarked lessons reads as no attendance, not 0", async () => {
  stub({
    ...DATA,
    classes: [{ ...DATA.classes[0], present: 0, absent: 0, not_taken: 2, rate: null }],
  });
  renderPanel({ studentId: 2 });
  expect(await screen.findByText(NO_ATTENDANCE)).toBeTruthy();
});

test("a student reads their own record from the token, never by id", async () => {
  const urls = stub(EMPTY);
  renderPanel({ studentId: 7, own: true });
  await screen.findByText(NO_ATTENDANCE);
  expect(urls).toEqual(["/api/v1/me/attendance"]);
});

test("a malformed response shows the load-failed message instead of crashing", async () => {
  stub([]);
  renderPanel({ studentId: 2 });
  expect(await screen.findByText(/usually temporary/)).toBeTruthy();
  expect(screen.getByRole("heading", { name: /attendance/i })).toBeTruthy();
});

test("a tutor or parent reads by student id", async () => {
  const urls = stub(EMPTY);
  renderPanel({ studentId: 7 });
  await screen.findByText(NO_ATTENDANCE);
  expect(urls).toEqual(["/api/v1/students/7/attendance"]);
});
