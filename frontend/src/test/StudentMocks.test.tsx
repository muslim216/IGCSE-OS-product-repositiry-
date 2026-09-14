import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import SitMockPage from "../student/SitMockPage";

const mock = {
  id: 7,
  subject_id: 1,
  group_id: 2,
  title: "Chemistry Mock — Paper 2",
  type: "mock",
  sat_on: null,
  status: "published",
  total_marks: 80,
  duration_minutes: 90,
  paper_name: "paper.pdf",
  mark_scheme_name: null,
  extraction_error: null,
  question_count: 12,
  questions: [],
};

const lateSubmission = {
  submission_id: 31,
  mock_id: 7,
  title: mock.title,
  subject_name: "Chemistry",
  status: "being_marked",
  submitted_at: "2026-09-14T10:00:00Z",
  measured_minutes: 97,
  submitted_late: true,
  raw_marks: null,
  max_marks: null,
};

/** Counts the calls to POST /open so a test can assert the clock is started
 *  once, not once per render — starting it twice is what the server's
 *  idempotency protects against, and the page must not lean on that. */
let openCalls = 0;

function mockFetch(clock: unknown, submission: unknown = null) {
  openCalls = 0;
  let current = submission;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      // Most specific first — "/mocks/7" is a substring of every other path.
      if (url.includes("/open")) {
        openCalls += 1;
        return new Response(JSON.stringify(clock), { status: 200 });
      }
      if (url.includes("/my-submission")) {
        return new Response(JSON.stringify(current), { status: 200 });
      }
      if (url.includes("/submissions") && init?.method === "POST") {
        current = lateSubmission;
        return new Response(JSON.stringify(lateSubmission), { status: 200 });
      }
      if (url.includes("/mocks/7")) {
        return new Response(JSON.stringify(mock), { status: 200 });
      }
      return new Response(JSON.stringify(null), { status: 200 });
    }),
  );
}

function renderSit() {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter initialEntries={["/student/mocks/7"]}>
        <Routes>
          <Route path="/student/mocks/:mockId" element={<SitMockPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  localStorage.setItem("avora-tokens", JSON.stringify({ access_token: "t", token_type: "bearer" }));
});

afterEach(() => {
  localStorage.clear();
  vi.unstubAllGlobals();
});

test("opening a mock starts the clock exactly once", async () => {
  mockFetch({
    opened_at: "2026-09-14T09:00:00Z",
    due_at: "2026-09-14T10:30:00Z",
    seconds_remaining: 5400,
    overdue: false,
  });
  renderSit();
  expect(await screen.findByText("Chemistry Mock — Paper 2")).toBeInTheDocument();
  await waitFor(() => expect(openCalls).toBe(1));
  expect(openCalls).toBe(1);
});

test("a running clock shows how long is left", async () => {
  mockFetch({
    opened_at: "2026-09-14T09:00:00Z",
    due_at: "2026-09-14T10:30:00Z",
    seconds_remaining: 3725,
    overdue: false,
  });
  renderSit();
  expect(await screen.findByText("Time left")).toBeInTheDocument();
  expect(screen.getByText(/^1:0[12]:0\d$/)).toBeInTheDocument();
});

test("a mock with no duration shows no countdown rather than a zero", async () => {
  // `seconds_remaining` is null when the tutor set no time limit. A "0:00" or
  // an empty bar would be an invented measurement (PROD-2, UX-19).
  mockFetch({
    opened_at: "2026-09-14T09:00:00Z",
    due_at: null,
    seconds_remaining: null,
    overdue: false,
  });
  renderSit();
  expect(await screen.findByText("Chemistry Mock — Paper 2")).toBeInTheDocument();
  expect(screen.queryByText("Time left")).not.toBeInTheDocument();
  expect(screen.queryByText(/0:00/)).not.toBeInTheDocument();
  expect(screen.queryByText(/Your time is up/)).not.toBeInTheDocument();
});

test("when the time is up the student is told and can still hand in", async () => {
  mockFetch({
    opened_at: "2026-09-14T09:00:00Z",
    due_at: "2026-09-14T10:30:00Z",
    seconds_remaining: 0,
    overdue: true,
  });
  renderSit();
  expect(await screen.findByText(/Your time is up/)).toBeInTheDocument();
  expect(screen.getByText(/You can still hand in/)).toBeInTheDocument();
  // The whole point of the feature: a late hand-in is accepted, never blocked.
  const button = screen.getByRole("button", { name: "Hand in" });
  fireEvent.change(screen.getByLabelText(/Or type your answers/), {
    target: { value: "my answers" },
  });
  expect(button).toBeEnabled();
});

test("a late hand-in tells the student it was flagged for their tutor", async () => {
  mockFetch({
    opened_at: "2026-09-14T09:00:00Z",
    due_at: "2026-09-14T10:30:00Z",
    seconds_remaining: 0,
    overdue: true,
  });
  renderSit();
  fireEvent.change(await screen.findByLabelText(/Or type your answers/), {
    target: { value: "my answers" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Hand in" }));

  expect(await screen.findByText(/flagged for your tutor/)).toBeInTheDocument();
  expect(screen.getByText("You took 97 minutes.")).toBeInTheDocument();
  expect(screen.getByText(/still\s+marked in full/)).toBeInTheDocument();
});

test("the countdown is the server's answer, not the browser's own tick", async () => {
  // The distinction this proves: a page that asks once and then counts down
  // locally forever would pass every other test here. It would also let a
  // student gain time by sleeping the laptop or moving the device clock, which
  // is the whole reason `AV-116` puts the clock on the server.
  vi.useFakeTimers({ shouldAdvanceTime: true });
  try {
    // The server's second answer says less time is left than a local tick
    // would have counted — 10 minutes, not the ~89 the first answer implies.
    let answers = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("/open")) {
          answers += 1;
          return new Response(
            JSON.stringify({
              opened_at: "2026-09-14T09:00:00Z",
              due_at: "2026-09-14T10:30:00Z",
              seconds_remaining: answers === 1 ? 5400 : 600,
              overdue: false,
            }),
            { status: 200 },
          );
        }
        if (url.includes("/my-submission")) {
          return new Response(JSON.stringify(null), { status: 200 });
        }
        if (url.includes("/mocks/7")) {
          return new Response(JSON.stringify(mock), { status: 200 });
        }
        return new Response(JSON.stringify(null), { status: 200 });
      }),
    );

    renderSit();
    expect(await screen.findByText(/90:00|1:30:00|89:5\d/)).toBeInTheDocument();

    // Past the re-ask interval.
    await vi.advanceTimersByTimeAsync(31_000);

    // The server's newer, smaller number wins over the local tick.
    await waitFor(() => expect(answers).toBeGreaterThan(1));
    await waitFor(() => expect(screen.getByText(/10:00|9:5\d/)).toBeInTheDocument());
  } finally {
    vi.useRealTimers();
  }
});
