import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, test, vi } from "vitest";
import LessonReminders from "../tutor/today/LessonReminders";

/* Task 7.4 (AV-120): the in-app reminder, with Review and a one-tap Cancel. */

const REMINDER = {
  slot_id: 7,
  group_id: 3,
  group_name: "Year 11 Chemistry",
  scheduled_date: "2026-10-13",
  start_time: "17:00:00",
  starts_at: new Date(Date.now() + 10 * 60_000).toISOString(),
  chapter: { id: 1, code: "4", title: "Organic chemistry" },
  topics: [
    { id: 11, code: "1.1", title: "Alkanes" },
    { id: 12, code: "1.2", title: "Alkenes" },
  ],
};

function stub(reminders: unknown[], cancelBody?: unknown) {
  const calls: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), "http://localhost");
      calls.push(`${init?.method ?? "GET"} ${url.pathname}`);
      const json = (b: unknown) => new Response(JSON.stringify(b), { status: 200 });
      if (url.pathname.endsWith("/today/reminders")) return json(reminders);
      if (url.pathname.endsWith("/cancel")) return json(cancelBody);
      return json(null);
    }),
  );
  return calls;
}

function renderIt() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <LessonReminders />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

test("shows the class, the time, what the plan covers and a Review link to the pre-filled form", async () => {
  stub([REMINDER]);
  renderIt();
  expect(await screen.findByText(/Year 11 Chemistry/)).toBeInTheDocument();
  expect(screen.getByText("17:00")).toBeInTheDocument();
  expect(screen.getByText(/Chapter 4 · Organic chemistry — Alkanes, Alkenes/)).toBeInTheDocument();
  expect(screen.getByText(/in 10 min/)).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Review the Year 11 Chemistry lesson" })).toHaveAttribute(
    "href",
    "/tutor/groups/3/schedule?slot=7",
  );
});

test("renders nothing when no lesson is about to start", async () => {
  stub([]);
  const { container } = (renderIt(), { container: document.body });
  await waitFor(() => expect(container.textContent).toBe(""));
});

test("Cancel is one tap and posts to the slot's cancel endpoint", async () => {
  const calls = stub([REMINDER], { shifted: true, moved: 3, message: null, plan: {} });
  renderIt();
  fireEvent.click(
    await screen.findByRole("button", { name: "Cancel the Year 11 Chemistry lesson" }),
  );
  await waitFor(() => expect(calls).toContain("POST /api/v1/groups/3/plan/slots/7/cancel"));
});

test("says so when there was no room before the exam, and keeps saying it after the row is gone", async () => {
  let reminders: unknown[] = [REMINDER];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), "http://localhost");
      const json = (b: unknown) => new Response(JSON.stringify(b), { status: 200 });
      if (url.pathname.endsWith("/today/reminders")) return json(reminders);
      if (url.pathname.endsWith("/cancel")) {
        reminders = [];
        return json({
          shifted: false,
          moved: 0,
          message: "No room before the exam — re-plan to catch up",
          plan: {},
        });
      }
      return json(null);
    }),
  );
  renderIt();
  fireEvent.click(
    await screen.findByRole("button", { name: "Cancel the Year 11 Chemistry lesson" }),
  );
  expect(await screen.findByRole("status")).toHaveTextContent("No room before the exam");
  await waitFor(() => expect(screen.queryByText(/Year 11 Chemistry/)).not.toBeInTheDocument());
  expect(screen.getByRole("status")).toHaveTextContent("re-plan to catch up");
});

test("a failed check says so, with a retry, instead of looking like nothing is coming up", async () => {
  let fail = true;
  vi.stubGlobal(
    "fetch",
    vi.fn(async () =>
      fail
        ? new Response(JSON.stringify({ detail: "down" }), { status: 500 })
        : new Response(JSON.stringify([REMINDER]), { status: 200 }),
    ),
  );
  renderIt();
  expect(await screen.findByText(/Couldn't check for upcoming lessons/)).toBeInTheDocument();
  fail = false;
  fireEvent.click(screen.getByRole("button", { name: "Retry" }));
  expect(await screen.findByText(/Year 11 Chemistry/)).toBeInTheDocument();
});
