import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import App from "../App";
import { AuthProvider } from "../auth/AuthContext";

/* T-039: the tutor menu is six items; the rest live inside each class or under
   the name menu. Every old address must still land somewhere sensible. */

const SUBJECT = { id: 1, exam_board: "CIE", code: "0625", name: "Physics", grade_scale: "9-1" };
const CLASS = (id: number) => ({
  id,
  name: `Physics ${id}`,
  subject: SUBJECT,
  member_count: 2,
  awaiting_review_count: 0,
  published_assignment_count: 0,
  next_lesson: null,
});

let calls: string[] = [];

function stub(role: "tutor" | "student" | "parent", classes: number) {
  calls = [];
  const user = { id: 1, email: "d@example.com", username: null, role, name: "Demo User" };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      calls.push(url);
      const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200 });
      if (url.includes("/auth/me")) return json(user);
      if (/\/api\/v1\/groups\/\d+$/.test(url)) return json(CLASS(Number(url.split("/").pop())));
      if (url.endsWith("/api/v1/groups")) {
        return json(Array.from({ length: classes }, (_, i) => CLASS(i + 5)));
      }
      return json([]);
    }),
  );
}

function Probe() {
  const l = useLocation();
  return <p data-testid="where">{l.pathname + l.search + l.hash}</p>;
}

function renderApp(entry: string) {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <AuthProvider>
        <MemoryRouter initialEntries={[entry]}>
          <App />
          <Probe />
        </MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>,
  );
}

const where = () => screen.getByTestId("where").textContent;

beforeEach(() => {
  localStorage.setItem("avora-tokens", JSON.stringify({ access_token: "t", token_type: "bearer" }));
});
afterEach(() => {
  localStorage.clear();
  vi.unstubAllGlobals();
});

test("the sidebar has six items in the owner's order", async () => {
  stub("tutor", 1);
  renderApp("/tutor");
  const sidebar = await screen.findByRole("navigation", { name: "Tutor navigation" });
  expect(
    within(sidebar)
      .getAllByRole("link")
      .map((l) => l.textContent),
  ).toEqual(["Today", "Mark", "Classes", "Students", "Mocks", "Library"]);
});

test("the name menu opens, takes the keyboard, and Escape returns focus to its button", async () => {
  stub("tutor", 1);
  renderApp("/tutor");
  const button = (await screen.findAllByRole("button", { name: /Demo User/ }))[0];
  expect(button).toHaveAttribute("aria-haspopup", "menu");
  expect(button).toHaveAttribute("aria-expanded", "false");
  fireEvent.click(button);
  const menu = await screen.findByRole("menu");
  const items = within(menu).getAllByRole("menuitem");
  expect(items.map((i) => i.textContent)).toEqual(["Subject setup", "Settings", "Sign out"]);
  expect(items[0]).toHaveFocus();
  fireEvent.keyDown(menu, { key: "ArrowDown" });
  expect(items[1]).toHaveFocus();
  fireEvent.keyDown(menu, { key: "End" });
  expect(items[2]).toHaveFocus();
  fireEvent.keyDown(document, { key: "Escape" });
  await waitFor(() => expect(screen.queryByRole("menu")).not.toBeInTheDocument());
  expect(button).toHaveFocus();
});

test("the name menu leads to Subject setup", async () => {
  stub("tutor", 1);
  renderApp("/tutor");
  fireEvent.click((await screen.findAllByRole("button", { name: /Demo User/ }))[0]);
  fireEvent.click(await screen.findByRole("menuitem", { name: "Subject setup" }));
  await waitFor(() => expect(where()).toBe("/tutor/subject-setup"));
});

test("a student and a parent keep the plain account link, with no name menu", async () => {
  stub("student", 1);
  const view = renderApp("/student");
  await screen.findAllByRole("link", { name: /Your account/ });
  expect(screen.queryByRole("button", { name: /Demo User/ })).not.toBeInTheDocument();
  view.unmount();
  stub("parent", 1);
  renderApp("/parent");
  await screen.findAllByRole("link", { name: /Your account/ });
  expect(screen.queryByRole("button", { name: /Demo User/ })).not.toBeInTheDocument();
});

test("the phone bar has four tabs and More, which holds only Mocks and Library", async () => {
  stub("tutor", 1);
  renderApp("/tutor");
  const bar = await screen.findByRole("navigation", { name: "Tutor tabs" });
  const tabs = within(bar).getAllByRole("link");
  expect(tabs.map((t) => t.textContent)).toEqual(["Today", "Mark", "Classes", "Students"]);
  const more = within(bar).getByRole("button", { name: /More/ });
  for (const target of [...tabs, more]) expect(target.className).toContain("min-h-[44px]");
  fireEvent.click(more);
  const items = within(await screen.findByRole("menu")).getAllByRole("menuitem");
  expect(items.map((i) => i.textContent)).toEqual(["Mocks", "Library"]);
  for (const item of items) expect(item.className).toContain("min-h-[44px]");
});

const ONE = [
  ["/tutor/homework", "/tutor/groups/5/homework"],
  ["/tutor/past-papers", "/tutor/groups/5/homework#past-papers"],
  ["/tutor/papers", "/tutor/groups/5/homework#past-papers"],
  ["/tutor/booklets", "/tutor/groups/5/homework#past-papers"],
  ["/tutor/readiness", "/tutor/groups/5/analytics#readiness"],
  ["/tutor/reports", "/tutor/groups/5/analytics#reports"],
  ["/tutor/past-papers?subject=7#paper-3", "/tutor/groups/5/homework?subject=7#paper-3"],
  ["/tutor/past-papers?subject=7", "/tutor/groups/5/homework?subject=7#past-papers"],
] as const;

test.each(ONE)("with one class, %s lands on %s", async (from, to) => {
  stub("tutor", 1);
  renderApp(from);
  await waitFor(() => expect(where()).toBe(to));
});

test.each([
  "/tutor/homework",
  "/tutor/past-papers",
  "/tutor/papers",
  "/tutor/booklets",
  "/tutor/readiness",
  "/tutor/reports",
])("with several classes, %s lands on the class list", async (from) => {
  stub("tutor", 2);
  renderApp(`${from}?subject=7#x`);
  await waitFor(() => expect(where()).toBe("/tutor/classes?subject=7#x"));
});

test.each([
  ["/tutor/reports/5", "/tutor/groups/5/analytics#reports"],
  ["/tutor/today", "/tutor"],
  ["/tutor/boundaries?subject=7", "/tutor/subject-setup?subject=7#boundaries"],
  ["/tutor/settings", "/tutor/settings"],
  ["/tutor/subject-setup?subject=7#boundaries", "/tutor/subject-setup?subject=7#boundaries"],
  ["/tutor/groups/5/analytics", "/tutor/groups/5/analytics"],
])("%s lands on %s whatever the class count", async (from, to) => {
  stub("tutor", 2);
  renderApp(from);
  await waitFor(() => expect(where()).toBe(to));
});

test("a student or a parent on a tutor path is turned away, and a tutor on a student path too", async () => {
  stub("student", 1);
  const a = renderApp("/tutor/classes");
  await waitFor(() => expect(where()).toBe("/student"));
  a.unmount();
  stub("parent", 1);
  const b = renderApp("/tutor/homework");
  await waitFor(() => expect(where()).toBe("/parent"));
  b.unmount();
  stub("tutor", 1);
  renderApp("/student/mocks/3");
  await waitFor(() => expect(where()).toBe("/tutor"));
});

test.each([
  ["/student/mocks/3", "/student/mocks"],
  ["/student/past-papers/3", "/student/past-papers"],
])("the sit page %s has no navigation and shows the exit link", async (path, leave) => {
  stub("student", 1);
  renderApp(path);
  const exit = await screen.findByRole("link", { name: "Leave the paper" });
  expect(exit).toHaveAttribute("href", leave);
  expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
});

test("the student list pages still have the menu", async () => {
  stub("student", 1);
  renderApp("/student/mocks");
  expect(await screen.findByRole("navigation", { name: "Student navigation" })).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "Leave the paper" })).not.toBeInTheDocument();
});

test("the class-list tip shows once, is the only notice, and stays dismissed", async () => {
  stub("tutor", 2);
  const first = renderApp("/tutor/past-papers");
  expect(await screen.findByText("Past papers now live inside each class.")).toBeInTheDocument();
  expect(screen.queryAllByRole("alert")).toHaveLength(0);
  fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
  expect(screen.queryByText("Past papers now live inside each class.")).not.toBeInTheDocument();
  first.unmount();

  stub("tutor", 2);
  renderApp("/tutor/past-papers");
  await screen.findByText("Physics 5");
  expect(screen.queryByText("Past papers now live inside each class.")).not.toBeInTheDocument();
});

test("the class page has six tabs, and lights Classes", async () => {
  stub("tutor", 1);
  renderApp("/tutor/groups/5/students");
  const tabs = await screen.findByRole("navigation", { name: "Class sections" });
  expect(
    within(tabs)
      .getAllByRole("link")
      .map((l) => l.textContent),
  ).toEqual(["Work", "Students", "Syllabus", "Schedule", "Resources", "Progress"]);
  const sidebar = screen.getByRole("navigation", { name: "Tutor navigation" });
  expect(within(sidebar).getByRole("link", { name: "Classes" })).toHaveAttribute(
    "aria-current",
    "page",
  );
});

test("an assignment page lights Classes, and there is no Homework item", async () => {
  stub("tutor", 1);
  renderApp("/tutor/assignments/5");
  const sidebar = await screen.findByRole("navigation", { name: "Tutor navigation" });
  expect(within(sidebar).getByRole("link", { name: "Classes" })).toHaveAttribute(
    "aria-current",
    "page",
  );
  expect(within(sidebar).queryByRole("link", { name: "Homework" })).not.toBeInTheDocument();
});

test("the Work tab asks for this class's subject only and links to Booklets", async () => {
  stub("tutor", 1);
  renderApp("/tutor/groups/5/homework");
  const section = await waitFor(() => {
    const el = document.getElementById("past-papers");
    expect(el).not.toBeNull();
    return el as HTMLElement;
  });
  expect(within(section).getByRole("link", { name: /Booklets/ })).toHaveAttribute(
    "href",
    "/tutor/past-papers/booklets",
  );
  await waitFor(() =>
    expect(calls.some((c) => c.includes("/past-papers?subject_id=1"))).toBe(true),
  );
  expect(calls.some((c) => c.endsWith("/api/v1/past-papers"))).toBe(false);
});

test("Progress shows one section at a time, with the hash in the URL, and no class picker", async () => {
  stub("tutor", 2);
  renderApp("/tutor/groups/5/analytics#readiness");
  const switcher = await screen.findByRole("navigation", { name: "Progress sections" });
  expect(within(switcher).getByRole("link", { name: "Readiness" })).toHaveAttribute(
    "aria-current",
    "true",
  );
  expect(screen.queryByRole("combobox", { name: "Class" })).not.toBeInTheDocument();
  expect(screen.queryByText("How often you agreed with the AI")).not.toBeInTheDocument();
  fireEvent.click(within(switcher).getByRole("link", { name: "Analytics" }));
  await waitFor(() => expect(where()).toBe("/tutor/groups/5/analytics"));
  expect(await screen.findByText("How often you agreed with the AI")).toBeInTheDocument();
  fireEvent.click(within(switcher).getByRole("link", { name: "Reports" }));
  await waitFor(() => expect(where()).toBe("/tutor/groups/5/analytics#reports"));
});

test("Booklets still opens at its new address", async () => {
  stub("tutor", 1);
  renderApp("/tutor/past-papers/booklets");
  expect(await screen.findByRole("heading", { level: 1 })).toBeInTheDocument();
  expect(where()).toBe("/tutor/past-papers/booklets");
});
