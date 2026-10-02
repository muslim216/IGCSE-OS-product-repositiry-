import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, test, vi } from "vitest";
import ReviewQueuePage from "../tutor/ReviewQueuePage";

/* The Review page says "nothing waiting" once, and only when it knows. */

function stub({ attentionFails = false } = {}) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), "http://localhost");
      if (url.pathname === "/api/v1/assignments/attention" && attentionFails) {
        return new Response(JSON.stringify({ detail: "boom" }), { status: 500 });
      }
      return new Response(JSON.stringify([]), { status: 200 });
    }),
  );
}

function renderPage() {
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter>
        <ReviewQueuePage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

test("an empty queue is said once, not as a card above an empty state", async () => {
  stub();
  renderPage();
  expect(await screen.findByText("You're all caught up.")).toBeInTheDocument();
  expect(screen.queryByText(/Nothing to review/)).not.toBeInTheDocument();
  expect(screen.queryByText("Needs your review")).not.toBeInTheDocument();
});

test("a failed second list never reads as all caught up", async () => {
  stub({ attentionFails: true });
  renderPage();
  expect(await screen.findByText(/didn't load/)).toBeInTheDocument();
  expect(screen.queryByText("You're all caught up.")).not.toBeInTheDocument();
});

test("a loaded queue is shown while the second list is still on its way", async () => {
  // One loading gate over both requests hid a queue that had already arrived
  // for as long as the attention list took.
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const path = new URL(String(input), "http://localhost").pathname;
      if (path === "/api/v1/assignments/attention") return new Promise<Response>(() => {});
      return new Response(
        JSON.stringify([
          {
            submission_id: 8,
            assignment_id: 2,
            past_paper_id: null,
            mock_id: null,
            assignment_title: "HW2 — Ionic bonding",
            student_id: 4,
            student_name: "Ali Rahman",
            submitted_at: "2026-10-01T10:00:00Z",
            unsure_count: 1,
            remark_request_count: 0,
          },
        ]),
        { status: 200 },
      );
    }),
  );
  renderPage();

  expect(await screen.findByText("HW2 — Ionic bonding")).toBeInTheDocument();
  // Nothing is claimed about the list that has not answered.
  expect(screen.queryByText("You're all caught up.")).not.toBeInTheDocument();
});

test("a submission already in the queue is not listed a second time below it", async () => {
  const queueItem = {
    submission_id: 8,
    assignment_id: 2,
    past_paper_id: null,
    mock_id: null,
    assignment_title: "HW2 — Ionic bonding",
    student_id: 4,
    student_name: "Ali Rahman",
    submitted_at: "2026-10-01T10:00:00Z",
    unsure_count: 1,
    remark_request_count: 0,
  };
  const attention = [
    // The same submission, as the attention list reports it.
    {
      assignment_id: 2,
      assignment_title: "HW2 — Ionic bonding",
      reason: "needs_review",
      detail: null,
      submission_id: 8,
      student_name: "Ali Rahman",
    },
    // Something only the attention list knows about.
    {
      assignment_id: 3,
      assignment_title: "HW3 — Moles",
      reason: "extraction_failed",
      detail: null,
      submission_id: null,
      student_name: null,
    },
  ];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const path = new URL(String(input), "http://localhost").pathname;
      if (path === "/api/v1/assignments/attention")
        return new Response(JSON.stringify(attention), { status: 200 });
      return new Response(JSON.stringify([queueItem]), { status: 200 });
    }),
  );
  renderPage();

  expect(await screen.findByText("HW3 — Moles")).toBeInTheDocument();
  // Listed once, in the queue — not again under "Needs your attention".
  expect(screen.getAllByText("HW2 — Ionic bonding")).toHaveLength(1);
});
