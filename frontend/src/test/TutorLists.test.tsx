import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, test, vi } from "vitest";
import StudentsPage from "../tutor/StudentsPage";

/* The cross-class Students list (9.3c). What has to hold: a failed
   load never reads as "none yet", absent data is worded rather than shown as 0,
   a cut-off list says so (on the server's word, not a number mirrored here), and
   the student search can tell "no students" from "no match". */

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
