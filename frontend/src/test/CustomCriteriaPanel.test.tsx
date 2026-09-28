import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, test, vi } from "vitest";
import CustomCriteriaPanel from "../components/CustomCriteriaPanel";

/* Tutor-entered criteria beside readiness (task 5.4c, owner decisions 6 and
   18). Every score is labelled as the tutor's (PROD-8), an unscored criterion
   reads "Not scored" and never 0 (PROD-2), and only a tutor can edit. */

const ROWS = [
  {
    criterion_id: 1,
    name: "Exam technique",
    description: null,
    subject_id: null,
    score: null,
    updated_at: null,
    updated_by_id: null,
    source: "tutor",
  },
  {
    criterion_id: 2,
    name: "Confidence",
    description: "In class",
    subject_id: null,
    score: 70,
    updated_at: "2026-09-20T10:00:00Z",
    updated_by_id: 1,
    source: "tutor",
  },
];

function stub(rows: unknown[], { conflict = false } = {}) {
  const calls: { method: string; url: string; body?: unknown }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), "http://localhost");
      const method = (init?.method ?? "GET").toUpperCase();
      const body = init?.body ? JSON.parse(String(init.body)) : undefined;
      calls.push({ method, url: url.pathname, body });
      if (method === "GET") return new Response(JSON.stringify(rows), { status: 200 });
      if (conflict)
        return new Response(JSON.stringify({ detail: "This criterion is archived." }), {
          status: 409,
        });
      if (method === "DELETE") return new Response(null, { status: 204 });
      return new Response(JSON.stringify({ ...ROWS[0], score: body.score }), { status: 200 });
    }),
  );
  return calls;
}

function renderPanel(editable: boolean) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <CustomCriteriaPanel studentId={2} editable={editable} />
    </QueryClientProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

test("an unscored criterion reads 'Not scored', never 0, and every row is labelled", async () => {
  stub(ROWS);
  renderPanel(false);

  const row = (await screen.findByText("Exam technique")).closest("li")!;
  expect(row.textContent).toContain("Not scored");
  expect(row.textContent).not.toMatch(/\b0\b/);
  expect(screen.getByText("70 / 100")).toBeTruthy();
  // One label per row, beside the heading.
  expect(screen.getAllByText("Tutor-entered")).toHaveLength(2);
  expect(screen.getByRole("heading", { name: /tutor-entered criteria/i })).toBeTruthy();
});

test("read-only has no inputs or buttons", async () => {
  stub(ROWS);
  renderPanel(false);
  await screen.findByText("Exam technique");
  expect(screen.queryByRole("spinbutton")).toBeNull();
  expect(screen.queryByRole("button")).toBeNull();
});

test("read-only renders nothing when there are no criteria", async () => {
  const calls = stub([]);
  const { container } = renderPanel(false);
  await waitFor(() => expect(calls.length).toBe(1));
  await waitFor(() => expect(container.textContent).toBe(""));
});

test("a tutor sees an empty state when there are no criteria", async () => {
  stub([]);
  renderPanel(true);
  expect(await screen.findByText(/no criteria yet/i)).toBeTruthy();
});

test("a tutor saves a score with a PUT", async () => {
  const calls = stub(ROWS);
  renderPanel(true);
  const input = await screen.findByRole("spinbutton", { name: /score for exam technique/i });
  fireEvent.change(input, { target: { value: "70" } });
  fireEvent.click(screen.getByRole("button", { name: /save score for exam technique/i }));

  await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
  const put = calls.find((c) => c.method === "PUT")!;
  expect(put.url).toBe("/api/v1/students/2/custom-criteria/1");
  expect(put.body).toEqual({ score: 70 });
});

test("a score outside 0-100 cannot be saved", async () => {
  stub(ROWS);
  renderPanel(true);
  const input = await screen.findByRole("spinbutton", { name: /score for exam technique/i });
  fireEvent.change(input, { target: { value: "101" } });
  const save = screen.getByRole("button", {
    name: /save score for exam technique/i,
  }) as HTMLButtonElement;
  expect(save.disabled).toBe(true);
});

test("a tutor clears a score with a DELETE", async () => {
  const calls = stub(ROWS);
  renderPanel(true);
  fireEvent.click(await screen.findByRole("button", { name: /clear score for confidence/i }));
  await waitFor(() =>
    expect(
      calls.some((c) => c.method === "DELETE" && c.url === "/api/v1/students/2/custom-criteria/2"),
    ).toBe(true),
  );
  // Nothing to clear on an unscored row.
  expect(screen.queryByRole("button", { name: /clear score for exam technique/i })).toBeNull();
});

test("the server's 409 is shown inline", async () => {
  stub(ROWS, { conflict: true });
  renderPanel(true);
  const input = await screen.findByRole("spinbutton", { name: /score for exam technique/i });
  fireEvent.change(input, { target: { value: "5" } });
  fireEvent.click(screen.getByRole("button", { name: /save score for exam technique/i }));
  expect((await screen.findByRole("alert")).textContent).toMatch(/archived/i);
});
