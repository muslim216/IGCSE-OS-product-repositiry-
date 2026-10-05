import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, test, vi } from "vitest";
import HomeworkPage from "../tutor/HomeworkPage";
import StudentsPage from "../tutor/StudentsPage";
import { formatDayMonth } from "../lib/timezones";

/* The cross-class Homework and Students lists (9.3c). What has to hold: a failed
   load never reads as "none yet", absent data is worded rather than shown as 0,
   a cut-off list says so (on the server's word, not a number mirrored here), and
   the student search can tell "no students" from "no match". */

const homework = (over: object) => ({
  id: 1,
  title: "Bonding worksheet",
  status: "published",
  due_at: "2026-10-12T10:00:00Z",
  created_at: "2026-10-01T10:00:00Z",
  group_id: 4,
  group_name: "Chem Y10",
  subject_name: "Chemistry",
  enrolled_count: 5,
  submitted_count: 3,
  marked_count: 2,
  ...over,
});

const student = (id: number, name: string, classes: string[]) => ({
  id,
  name,
  classes: classes.map((c, i) => ({ group_id: i + 1, group_name: c, subject_name: "Chemistry" })),
});

const list = (items: object[], over: object = {}) => ({
  items,
  truncated: false,
  limit: 200,
  ...over,
});

function serve(path: string, body: unknown, extra: Record<string, unknown> = {}) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), "http://localhost");
      if (url.pathname in extra)
        return new Response(JSON.stringify(extra[url.pathname]), { status: 200 });
      if (url.pathname !== path) return new Response(JSON.stringify([]), { status: 200 });
      return body === "fail"
        ? new Response(JSON.stringify({ detail: "boom" }), { status: 500 })
        : new Response(JSON.stringify(body), { status: 200 });
    }),
  );
}

function renderPage(page: React.ReactElement) {
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter>{page}</MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

// --- Homework ----------------------------------------------------------------

test("homework shows a loading state, then its rows linking to the assignment", async () => {
  serve("/api/v1/assignments", list([homework({})]));
  renderPage(<HomeworkPage />);
  expect(screen.getByRole("status", { name: "Loading homework" })).toBeInTheDocument();
  const link = await screen.findByRole("link", { name: /Bonding worksheet/ });
  expect(link).toHaveAttribute("href", "/tutor/assignments/1");
  expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
  const row = within(link);
  expect(row.getByText(/Chem Y10/)).toBeInTheDocument();
  expect(row.getByText("3 of 5 handed in · 2 marked")).toBeInTheDocument();
  // The same words the class homework tab uses.
  expect(row.getByText("Published")).toBeInTheDocument();
});

test("homework with no due date and no students says so instead of printing zeros", async () => {
  serve(
    "/api/v1/assignments",
    list([homework({ due_at: null, enrolled_count: 0, submitted_count: 0, marked_count: 0 })]),
  );
  renderPage(<HomeworkPage />);
  const link = await screen.findByRole("link", { name: /Bonding worksheet/ });
  expect(within(link).getByText(/No due date/)).toBeInTheDocument();
  expect(within(link).getByText("No students yet")).toBeInTheDocument();
  expect(link.textContent).not.toMatch(/0 of 0/);
});

test("a published homework nobody has handed in yet shows a real zero", async () => {
  serve(
    "/api/v1/assignments",
    list([homework({ enrolled_count: 4, submitted_count: 0, marked_count: 0 })]),
  );
  renderPage(<HomeworkPage />);
  const link = await screen.findByRole("link", { name: /Bonding worksheet/ });
  expect(within(link).getByText("0 of 4 handed in · 0 marked")).toBeInTheDocument();
});

test("a draft shows its status, not hand-in counts", async () => {
  serve(
    "/api/v1/assignments",
    list([homework({ status: "review", enrolled_count: 5, submitted_count: 0, marked_count: 0 })]),
  );
  renderPage(<HomeworkPage />);
  const link = await screen.findByRole("link", { name: /Bonding worksheet/ });
  expect(within(link).getByText("Check the questions")).toBeInTheDocument();
  expect(link.textContent).not.toMatch(/handed in/);
});

test("no homework points at Classes, where it is set", async () => {
  serve("/api/v1/assignments", list([]));
  renderPage(<HomeworkPage />);
  expect(await screen.findByText("No homework yet")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Go to Classes" })).toHaveAttribute(
    "href",
    "/tutor/classes",
  );
});

test("a failed homework load is an error with a retry, not an empty list", async () => {
  serve("/api/v1/assignments", "fail");
  renderPage(<HomeworkPage />);
  expect(await screen.findByText("Couldn't load your homework")).toBeInTheDocument();
  expect(screen.queryByText("No homework yet")).not.toBeInTheDocument();
});

test("a truncated homework list says so, naming the server's cap", async () => {
  serve(
    "/api/v1/assignments",
    list([homework({ id: 1, title: "HW 1" })], { truncated: true, limit: 150 }),
  );
  renderPage(<HomeworkPage />);
  await screen.findByRole("link", { name: /HW 1\b/ });
  expect(screen.getByText(/Showing the 150 most recent/)).toBeInTheDocument();
});

test("a list that is exactly full but not truncated carries no cut-off note", async () => {
  serve("/api/v1/assignments", list([homework({})], { truncated: false, limit: 1 }));
  renderPage(<HomeworkPage />);
  await screen.findByRole("link", { name: /Bonding worksheet/ });
  expect(screen.queryByText(/Showing the/)).not.toBeInTheDocument();
});

test("a long unbroken class name wraps instead of overflowing", async () => {
  serve("/api/v1/assignments", list([homework({ group_name: "A".repeat(80) })]));
  renderPage(<HomeworkPage />);
  const link = await screen.findByRole("link", { name: /Bonding worksheet/ });
  expect(within(link).getByText(/AAAA/).className).toContain("break-words");
});

test("the due date is read in the organization's zone, near midnight", async () => {
  // 23:30 UTC on the 12th is already the 13th in Dubai (UTC+4).
  const due = "2026-10-12T23:30:00Z";
  const inDubai = formatDayMonth(new Date(due), "Asia/Dubai");
  const inUtc = formatDayMonth(new Date(due), "UTC");
  expect(inDubai).not.toEqual(inUtc);
  serve("/api/v1/assignments", list([homework({ due_at: due })]), {
    "/api/v1/me/organization": { id: 1, name: "Org", timezone: "Asia/Dubai" },
  });
  renderPage(<HomeworkPage />);
  const link = await screen.findByRole("link", { name: /Bonding worksheet/ });
  await vi.waitFor(() => expect(link.textContent).toContain(`Due ${inDubai}`));
  expect(link.textContent).not.toContain(`Due ${inUtc}`);
});

// --- Students ----------------------------------------------------------------

test("students lists each with their classes, linking to the student", async () => {
  serve(
    "/api/v1/students",
    list([student(7, "Ann", ["Chem A", "Chem B"]), student(9, "Ben", ["Chem A"])]),
  );
  renderPage(<StudentsPage />);
  expect(screen.getByRole("status", { name: "Loading students" })).toBeInTheDocument();
  const ann = await screen.findByRole("link", { name: /Ann/ });
  expect(ann).toHaveAttribute("href", "/tutor/students/7");
  expect(within(ann).getByText("Chem A, Chem B")).toBeInTheDocument();
  expect(within(ann).getByText("Chem A, Chem B").className).toContain("break-words");
  expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
  expect(screen.getAllByRole("listitem")).toHaveLength(2);
});

test("search filters by name and announces the count politely", async () => {
  serve("/api/v1/students", list([student(7, "Ann", ["Chem A"]), student(9, "Ben", ["Chem A"])]));
  renderPage(<StudentsPage />);
  await screen.findByRole("link", { name: /Ann/ });
  fireEvent.change(screen.getByLabelText("Search students"), { target: { value: "be" } });
  expect(screen.queryByRole("link", { name: /Ann/ })).not.toBeInTheDocument();
  expect(screen.getByRole("link", { name: /Ben/ })).toBeInTheDocument();
  const live = screen.getByRole("status");
  expect(live).toHaveAttribute("aria-live", "polite");
  expect(live).toHaveTextContent("1 student matches");
});

test("search ignores surrounding whitespace", async () => {
  serve("/api/v1/students", list([student(7, "Ann", ["Chem A"]), student(9, "Ben", ["Chem A"])]));
  renderPage(<StudentsPage />);
  await screen.findByRole("link", { name: /Ann/ });
  fireEvent.change(screen.getByLabelText("Search students"), { target: { value: "  ann  " } });
  expect(screen.getByRole("link", { name: /Ann/ })).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: /Ben/ })).not.toBeInTheDocument();
  // Only spaces is not a search: everyone stays listed.
  fireEvent.change(screen.getByLabelText("Search students"), { target: { value: "   " } });
  expect(screen.getAllByRole("listitem")).toHaveLength(2);
});

test("a search with no match is not the same as having no students", async () => {
  serve("/api/v1/students", list([student(7, "Ann", ["Chem A"])]));
  renderPage(<StudentsPage />);
  await screen.findByRole("link", { name: /Ann/ });
  fireEvent.change(screen.getByLabelText("Search students"), { target: { value: "zzz" } });
  expect(screen.getByText("No students match that name")).toBeInTheDocument();
  expect(screen.queryByText("No students yet")).not.toBeInTheDocument();
  // The box stays so the tutor can correct it.
  expect(screen.getByLabelText("Search students")).toBeInTheDocument();
});

test("no students points at Classes, where invites are made", async () => {
  serve("/api/v1/students", list([]));
  renderPage(<StudentsPage />);
  expect(await screen.findByText("No students yet")).toBeInTheDocument();
  expect(screen.getByText(/join through a class invite/)).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Go to Classes" })).toHaveAttribute(
    "href",
    "/tutor/classes",
  );
  expect(screen.queryByLabelText("Search students")).not.toBeInTheDocument();
});

test("a failed students load is an error, not an empty list", async () => {
  serve("/api/v1/students", "fail");
  renderPage(<StudentsPage />);
  expect(await screen.findByText("Couldn't load your students")).toBeInTheDocument();
  expect(screen.queryByText("No students yet")).not.toBeInTheDocument();
});

test("a truncated students list says so, naming the server's cap", async () => {
  serve(
    "/api/v1/students",
    list([student(1, "Student 1", ["Chem A"])], { truncated: true, limit: 300 }),
  );
  renderPage(<StudentsPage />);
  await screen.findByRole("link", { name: /Student 1\b/ });
  expect(screen.getByText(/Showing the first 300 students/)).toBeInTheDocument();
});

test("a full but untruncated students list has no note", async () => {
  serve("/api/v1/students", list([student(1, "Student 1", ["Chem A"])], { limit: 1 }));
  renderPage(<StudentsPage />);
  await screen.findByRole("link", { name: /Student 1\b/ });
  expect(screen.queryByText(/Showing the first/)).not.toBeInTheDocument();
});
