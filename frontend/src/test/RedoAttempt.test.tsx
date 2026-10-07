import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, test, vi } from "vitest";
import { RedoAttempt } from "../tutor/RedoAttempt";
import SubmissionReviewPage from "../tutor/SubmissionReviewPage";

/* "Let them redo this": the tutor's way out when a locked attempt was the wrong
   file. The button is the server's call (`can_redo`), the dialog says what will
   happen in words, and a refusal is shown rather than swallowed. */

function submissionBody(canRedo: boolean) {
  return {
    id: 1,
    assignment_id: 7,
    past_paper_id: null,
    mock_id: null,
    assignment_title: "HW1",
    student_id: 2,
    student_name: "Sara Ahmed",
    status: "auto_finalized",
    ai_error: null,
    submitted_at: "2026-06-01T10:00:00Z",
    files: [],
    typed_answer: null,
    subject_id: 3,
    marks: [],
    bare_question_count: 0,
    mistakes_analysed: true,
    can_redo: canRedo,
  };
}

type Respond = (path: string, method: string) => Response;

function stub(respond: Respond) {
  const fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) =>
    respond(
      new URL(String(input), "http://localhost").pathname,
      (init?.method ?? "GET").toUpperCase(),
    ),
  );
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

const RECEIPT = {
  id: 5,
  created_at: "2026-10-07T10:00:00Z",
  allowed_by_id: 1,
  allowed_by_name: "Test Tutor",
  work_kind: "homework",
  work_title: "HW1",
  previous_final_marks: 5,
  previous_max_marks: 6,
};

function renderPage(canRedo: boolean, redoResponse: () => Response = () => json(RECEIPT, 201)) {
  const fetch = stub((path, method) => {
    if (path === "/api/v1/submissions/1" && method === "GET") return json(submissionBody(canRedo));
    if (path === "/api/v1/submissions/1/redo" && method === "POST") return redoResponse();
    return json({ detail: "not stubbed" }, 404);
  });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const invalidate = vi.spyOn(client, "invalidateQueries");
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/tutor/submissions/1"]}>
        <Routes>
          <Route path="/tutor/submissions/:submissionId" element={<SubmissionReviewPage />} />
          <Route path="/tutor/assignments/:id" element={<p>Back on the assignment</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { fetch, invalidate };
}

function redoCalls(fetch: ReturnType<typeof stub>) {
  return fetch.mock.calls.filter(([url]) => String(url).endsWith("/redo"));
}

afterEach(() => vi.unstubAllGlobals());

test("the button is not offered when the attempt is not locked", async () => {
  renderPage(false);
  await screen.findByText("Sara Ahmed's work");
  expect(screen.queryByRole("button", { name: "Let them redo this" })).not.toBeInTheDocument();
});

test("the dialog names the student, says what will happen, and Cancel has focus", async () => {
  renderPage(true);
  fireEvent.click(await screen.findByRole("button", { name: "Let them redo this" }));

  const dialog = screen.getByRole("dialog", { name: "Let Sara redo this?" });
  expect(dialog).toHaveTextContent("They will be able to hand this in again.");
  expect(dialog).toHaveTextContent("stop counting toward readiness and cannot be brought back");
  expect(dialog).toHaveTextContent("A record of them is kept.");
  expect(screen.getByRole("button", { name: "Cancel" })).toHaveFocus();
});

test("Cancel closes the dialog and asks nothing of the server", async () => {
  const { fetch } = renderPage(true);
  fireEvent.click(await screen.findByRole("button", { name: "Let them redo this" }));
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  expect(redoCalls(fetch)).toHaveLength(0);
});

test("confirming sends the redo, refreshes what lists work, and goes back", async () => {
  const { fetch, invalidate } = renderPage(true);
  fireEvent.click(await screen.findByRole("button", { name: "Let them redo this" }));
  fireEvent.click(screen.getByRole("button", { name: "Let them redo it" }));

  expect(await screen.findByText("Back on the assignment")).toBeInTheDocument();
  const calls = redoCalls(fetch);
  expect(calls).toHaveLength(1);
  const [url, init] = calls[0] as unknown as [string, RequestInit];
  expect(url).toBe("/api/v1/submissions/1/redo");
  expect(init.method).toBe("POST");
  const refreshed = invalidate.mock.calls.map((c) => (c[0]?.queryKey as string[])[0]);
  for (const key of [
    "review-queue",
    "submissions",
    "assignment",
    "student-readiness",
    "class-overview",
    "analytics",
    "topic-evidence",
    "activity",
    "students",
  ]) {
    expect(refreshed).toContain(key);
  }
});

test("a refusal from the server is shown and the dialog stays open", async () => {
  const message = "This attempt has no final mark yet, so the student can already replace it.";
  renderPage(true, () => json({ detail: message }, 409));
  fireEvent.click(await screen.findByRole("button", { name: "Let them redo this" }));
  fireEvent.click(screen.getByRole("button", { name: "Let them redo it" }));

  expect(await screen.findByRole("alert")).toHaveTextContent(message);
  expect(screen.getByRole("dialog")).toBeInTheDocument();
});

test("a failed attempt does not leave the page", async () => {
  const onDone = vi.fn();
  stub(() => json({ detail: "boom" }, 500));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <RedoAttempt submissionId={1} studentName="Sara Ahmed" onDone={onDone} />
    </QueryClientProvider>,
  );
  fireEvent.click(screen.getByRole("button", { name: "Let them redo this" }));
  fireEvent.click(screen.getByRole("button", { name: "Let them redo it" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("Something went wrong on our side");
  expect(onDone).not.toHaveBeenCalled();
});

test("while the request is in flight Cancel is off and the dialog cannot be dismissed", async () => {
  let release: (r: Response) => void = () => {};
  const held = new Promise<Response>((resolve) => {
    release = resolve;
  });
  const fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = new URL(String(input), "http://localhost").pathname;
    if (path.endsWith("/redo") && init?.method === "POST") return held;
    return json(submissionBody(true));
  });
  vi.stubGlobal("fetch", fetch);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <RedoAttempt submissionId={1} studentName="Sara Ahmed" onDone={() => {}} />
    </QueryClientProvider>,
  );
  fireEvent.click(screen.getByRole("button", { name: "Let them redo this" }));
  fireEvent.click(screen.getByRole("button", { name: "Let them redo it" }));

  const cancel = await screen.findByRole("button", { name: "Cancel" });
  await waitFor(() => expect(cancel).toBeDisabled());
  fireEvent.click(cancel);
  fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
  expect(screen.getByRole("dialog")).toBeInTheDocument();

  release(json(RECEIPT, 201));
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
});
