import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, test, vi } from "vitest";
import AttendanceRegister from "../tutor/AttendanceRegister";

/* Task 7.1: the in-person register. Unmarked reads "Not taken", never absent. */

type Row = { student_id: number; name: string; state: string | null };

function stub(rows: Row[]) {
  const puts: unknown[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      if ((init?.method ?? "GET").toUpperCase() === "PUT") {
        const body = JSON.parse(String(init?.body));
        puts.push(body);
        for (const e of body.entries) {
          const row = rows.find((r) => r.student_id === e.student_id);
          if (row) row.state = e.state;
        }
      }
      return new Response(
        JSON.stringify(rows.map((r) => ({ ...r, source: null, recorded_at: null }))),
        { status: 200 },
      );
    }),
  );
  return puts;
}

function renderRegister() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <AttendanceRegister lessonId={9} />
    </QueryClientProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

test("an unmarked student shows Not taken and is never labelled absent", async () => {
  stub([
    { student_id: 1, name: "Sara", state: null },
    { student_id: 2, name: "Omar", state: "present" },
  ]);
  renderRegister();
  await screen.findByText("Sara");
  expect(screen.getAllByText("Not taken")).toHaveLength(1);
  expect(screen.getByRole("button", { name: "Present: Omar" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  expect(screen.getByRole("button", { name: "Absent: Sara" })).toHaveAttribute(
    "aria-pressed",
    "false",
  );
});

test("marking sends one entry, and pressing the active choice again clears it", async () => {
  const puts = stub([{ student_id: 1, name: "Sara", state: null }]);
  renderRegister();
  fireEvent.click(await screen.findByRole("button", { name: "Absent: Sara" }));
  await waitFor(() => expect(puts[0]).toEqual({ entries: [{ student_id: 1, state: "absent" }] }));
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Absent: Sara" })).toHaveAttribute(
      "aria-pressed",
      "true",
    ),
  );
  fireEvent.click(screen.getByRole("button", { name: "Absent: Sara" }));
  await waitFor(() => expect(puts[1]).toEqual({ entries: [{ student_id: 1, state: null }] }));
  expect(await screen.findByText("Not taken")).toBeInTheDocument();
});

test("a class with no students says so", async () => {
  stub([]);
  renderRegister();
  expect(await screen.findByText("No students in this class yet.")).toBeInTheDocument();
});
