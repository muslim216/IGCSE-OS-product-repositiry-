import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, test, vi } from "vitest";
import { EarlierAttempts } from "../tutor/EarlierAttempts";

/* The attempts a tutor set aside, on the student's page. A missing number is
   shown as missing, never as 0 (PROD-2). */

const base = {
  created_at: "2026-10-07T10:00:00Z",
  allowed_by_id: 1,
  allowed_by_name: "Test Tutor",
  work_kind: "homework",
  previous_questions_marked: 3,
  previous_question_count: 3,
};

function renderWith(respond: () => Response) {
  const fetch = vi.fn(async () => respond());
  vi.stubGlobal("fetch", fetch);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <EarlierAttempts studentId={9} />
    </QueryClientProvider>,
  );
  return fetch;
}

afterEach(() => vi.unstubAllGlobals());

test("lists each earlier attempt, with marks when there are marks", async () => {
  const fetch = renderWith(
    () =>
      new Response(
        JSON.stringify([
          {
            ...base,
            id: 2,
            work_title: "Atomic structure",
            previous_final_marks: 12,
            previous_max_marks: 20,
          },
        ]),
        { status: 200 },
      ),
  );

  expect(await screen.findByText("Atomic structure")).toBeInTheDocument();
  expect(screen.getByText("Earlier attempt: 12 of 20 — no longer counts")).toBeInTheDocument();
  expect(screen.getByText(/allowed by Test Tutor/)).toBeInTheDocument();
  const [url] = fetch.mock.calls[0] as unknown as [string];
  expect(url).toBe("/api/v1/students/9/redos");
});

test("says so, without a number, when the earlier attempt had no final marks", async () => {
  renderWith(
    () =>
      new Response(
        JSON.stringify([
          {
            ...base,
            id: 3,
            work_title: "Mock 1",
            previous_final_marks: null,
            previous_max_marks: null,
            previous_questions_marked: 0,
            previous_question_count: 3,
          },
        ]),
        { status: 200 },
      ),
  );

  expect(
    await screen.findByText("Earlier attempt was not fully marked — no longer counts"),
  ).toBeInTheDocument();
  // The whole rendered line, pinned: no "0 of 0", no "0%", nothing after the dash.
  const line = screen.getByText(/^Earlier attempt/);
  expect(line.textContent).toBe("Earlier attempt was not fully marked — no longer counts");
});

test("says how many questions the score covers when only some were marked", async () => {
  renderWith(
    () =>
      new Response(
        JSON.stringify([
          {
            ...base,
            id: 4,
            work_title: "Paper 2",
            previous_final_marks: 2,
            previous_max_marks: 2,
            previous_questions_marked: 1,
            previous_question_count: 3,
          },
        ]),
        { status: 200 },
      ),
  );

  const line = await screen.findByText(/^Earlier attempt/);
  expect(line.textContent).toBe(
    "Earlier attempt: 2 of 2 on the 1 of 3 questions marked — no longer counts",
  );
});

test("shows nothing at all when there are none", async () => {
  const fetch = renderWith(() => new Response("[]", { status: 200 }));

  await waitFor(() => expect(fetch).toHaveBeenCalled());
  await waitFor(() => expect(screen.queryByText("Attempts set aside")).not.toBeInTheDocument());
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

test("a failed load says so rather than looking like an empty record", async () => {
  renderWith(() => new Response(JSON.stringify({ detail: "x" }), { status: 500 }));

  expect(await screen.findByRole("alert")).toHaveTextContent("Could not load the attempts");
});
