import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import App from "../App";
import { AuthProvider } from "../auth/AuthContext";

function mockAuthedFetch(role: "student" | "tutor") {
  const user = { id: 1, email: "demo@example.com", username: null, role, name: "Demo User" };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/v1/auth/me")) {
        return new Response(JSON.stringify(user), { status: 200 });
      }
      return new Response(JSON.stringify([]), { status: 200 });
    }),
  );
}

function renderApp(entry: string) {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <AuthProvider>
        <MemoryRouter initialEntries={[entry]}>
          <App />
        </MemoryRouter>
      </AuthProvider>
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

// The nav renders twice in the DOM (desktop sidebar + mobile top bar, toggled
// purely via CSS media queries), so every label legitimately matches twice.
async function expectNavLabel(label: string) {
  expect((await screen.findAllByText(label)).length).toBeGreaterThan(0);
}

test("every student destination is reachable from the nav", async () => {
  mockAuthedFetch("student");
  renderApp("/student");
  for (const label of [
    "Home",
    // "Progress", not "Readiness" — the destination is named for what the
    // reader gets, not for the engine behind one of its numbers.
    "Progress",
    "Files",
    "Recordings",
    "Homework",
    "Past papers",
    "Exams",
  ]) {
    await expectNavLabel(label);
  }
});

test("the old Readiness URL still lands, on Progress", async () => {
  const user = { id: 1, email: "d@e.com", username: null, role: "student", name: "Demo" };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/v1/auth/me"))
        return new Response(JSON.stringify(user), { status: 200 });
      if (url.includes("/api/v1/readiness/me")) {
        return new Response(JSON.stringify({ student_id: 1, student_name: "Demo", subjects: [] }), {
          status: 200,
        });
      }
      return new Response(JSON.stringify([]), { status: 200 });
    }),
  );
  renderApp("/student/readiness");
  // A renamed destination must not 404 a bookmark: the route redirects rather
  // than disappearing (edge case 20). Landing on Progress's own empty state is
  // the proof — the old URL rendered a page, not the marketing site.
  expect(await screen.findByText("No progress to show yet.")).toBeInTheDocument();
});

test("the tutor nav has seven destinations in the owner's order", async () => {
  mockAuthedFetch("tutor");
  renderApp("/tutor");
  const sidebar = await screen.findByRole("navigation", { name: "Tutor navigation" });
  const labels = within(sidebar)
    .getAllByRole("link")
    .map((link) => link.textContent);
  expect(labels).toEqual([
    "Today",
    "Classes",
    "Review",
    "Readiness",
    "Papers & mocks",
    "Library",
    "Settings",
  ]);
});

test("Readiness in the nav is the class readiness page", async () => {
  mockAuthedFetch("tutor");
  renderApp("/tutor");
  const sidebar = await screen.findByRole("navigation", { name: "Tutor navigation" });
  expect(within(sidebar).getByRole("link", { name: "Readiness" })).toHaveAttribute(
    "href",
    "/tutor/readiness",
  );
});

test("the Papers & mocks hub links to past papers, booklets and mocks", async () => {
  mockAuthedFetch("tutor");
  renderApp("/tutor/papers");
  for (const [label, href] of [
    ["Past papers", "/tutor/past-papers"],
    ["Booklets", "/tutor/booklets"],
    ["Mocks", "/tutor/mocks"],
  ]) {
    const card = (await screen.findAllByRole("link", { name: new RegExp(label) })).find(
      (link) => link.getAttribute("href") === href,
    );
    expect(card).toBeDefined();
  }
});

test("the Library lists only source material, not setup, readiness or papers", async () => {
  mockAuthedFetch("tutor");
  renderApp("/tutor/library");
  expect(await screen.findByRole("link", { name: /Syllabuses/ })).toBeInTheDocument();
  const main = screen.getByRole("main");
  for (const label of [
    "Past papers",
    "Mocks",
    "Class readiness",
    "Preferences",
    "Grade boundaries",
    "Teaching guidance",
  ]) {
    expect(within(main).queryByText(label)).not.toBeInTheDocument();
  }
});

test("Settings renders every section under its heading, in order", async () => {
  mockAuthedFetch("tutor");
  renderApp("/tutor/settings");
  await screen.findByRole("heading", { level: 1, name: "Settings" });
  const headings = screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent);
  const wanted = [
    "Teaching guidance",
    "AI marking agreement",
    "Grade boundaries",
    "Mistake categories",
    "Preferences",
    "Account and integrations",
  ];
  expect(wanted.map((w) => headings.indexOf(w))).toEqual(
    [...wanted.map((w) => headings.indexOf(w))].sort((a, b) => a - b),
  );
  for (const w of wanted) expect(headings).toContain(w);
  const index = screen.getByRole("navigation", { name: "Settings sections" });
  expect(within(index).getAllByRole("link")).toHaveLength(wanted.length);
});

test.each([
  ["teaching-guidance", "Teaching guidance"],
  ["marking-rules", "AI marking agreement"],
  ["boundaries", "Grade boundaries"],
  ["mistake-categories", "Mistake categories"],
  ["preferences", "Preferences"],
])("the old %s URL lands on Settings at that section", async (path, heading) => {
  mockAuthedFetch("tutor");
  const scroll = vi.fn();
  Element.prototype.scrollIntoView = scroll;
  renderApp(`/tutor/${path}`);
  expect(await screen.findByRole("heading", { level: 1, name: "Settings" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { level: 2, name: heading })).toBeInTheDocument();
  await waitFor(() => expect(scroll).toHaveBeenCalled());
  expect(scroll.mock.contexts[0]).toHaveProperty("id", path);
});

test("a nested page keeps its parent nav item active", async () => {
  mockAuthedFetch("tutor");
  renderApp("/tutor/syllabuses");
  const sidebar = await screen.findByRole("navigation", { name: "Tutor navigation" });
  const library = within(sidebar).getByRole("link", { name: "Library" });
  await waitFor(() => expect(library.className).toContain("bg-brand-600"));
  expect(within(sidebar).getByRole("link", { name: "Papers & mocks" }).className).not.toContain(
    "bg-brand-600",
  );
});

test("a past paper page highlights Papers & mocks", async () => {
  mockAuthedFetch("tutor");
  renderApp("/tutor/past-papers");
  const sidebar = await screen.findByRole("navigation", { name: "Tutor navigation" });
  const link = within(sidebar).getByRole("link", { name: "Papers & mocks" });
  await waitFor(() => expect(link.className).toContain("bg-brand-600"));
  expect(within(sidebar).getByRole("link", { name: "Library" }).className).not.toContain(
    "bg-brand-600",
  );
});

test("a bookmarked retired route lands on its successor, never a 404", async () => {
  // Homework overview folded into Review; the old URL redirects there.
  mockAuthedFetch("tutor");
  renderApp("/tutor/homework");
  // The Review page's own copy is unique, so seeing it proves the redirect
  // resolved to that page rather than bouncing to a 404 or the landing screen.
  expect(
    await screen.findByText(/You review only the marks the AI wasn't sure about/),
  ).toBeInTheDocument();
});

test("the mobile tab bar carries the main workflow and overflows the rest", async () => {
  // The bar holds MAX_TABS destinations and folds the remainder into More, so
  // the thumb reaches the daily loop without the bar becoming a scroll.
  //
  // This asserted the bottom-slot item stayed out of the bar until 0.3 deleted
  // "AI Tutor", which was the only one. AppShell still honours `slot: "bottom"`
  // — nothing uses it today.
  mockAuthedFetch("student");
  renderApp("/student");
  const tabBar = await screen.findByRole("navigation", { name: "Student tabs" });
  expect(within(tabBar).getByText("Home")).toBeInTheDocument();
  // Overflow exists because the student has more destinations than the bar holds.
  expect(within(tabBar).getByRole("button", { name: /More/ })).toBeInTheDocument();
});

test("every nav destination remains reachable on mobile via More", async () => {
  mockAuthedFetch("student");
  renderApp("/student");
  const tabBar = await screen.findByRole("navigation", { name: "Student tabs" });
  fireEvent.click(within(tabBar).getByRole("button", { name: /More/ }));
  const menu = await screen.findByRole("menu");
  // The destinations that don't fit the bar are all present in the overflow
  // sheet — nothing becomes unreachable by being pushed out of it.
  for (const label of ["Exams", "Files", "Recordings"]) {
    expect(within(menu).getByText(label)).toBeInTheDocument();
  }
});

test("the sidebar has no self-link", async () => {
  // "AI Guidance" pointed at /tutor from the sidebar of /tutor itself. A nav
  // item that navigates nowhere is a broken promise, so it is gone — and the
  // destination it advertised never existed to begin with.
  mockAuthedFetch("tutor");
  renderApp("/tutor");
  await screen.findAllByText("Today");
  expect(screen.queryByText("AI Guidance")).not.toBeInTheDocument();
});
