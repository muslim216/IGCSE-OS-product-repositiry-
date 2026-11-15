import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import App from "../App";
import { AuthProvider } from "../auth/AuthContext";

const EMPTY_TODAY = {
  class_count: 0,
  joined_student_count: 0,
  classes_with_evidence: 0,
  classes: [],
  lessons: [],
  review_count: 0,
  chapter_prompts: [],
  behind_classes: [],
};

function mockAuthedFetch(role: "student" | "tutor") {
  const user = { id: 1, email: "demo@example.com", username: null, role, name: "Demo User" };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/v1/auth/me")) {
        return new Response(JSON.stringify(user), { status: 200 });
      }
      if (url.endsWith("/api/v1/today")) {
        // The empty-account shape: Today renders without crashing (the onboarding
        // read below answers with a list, so it falls back to the plain empty state).
        return new Response(JSON.stringify(EMPTY_TODAY), { status: 200 });
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

test("a submission page keeps Mark lit", async () => {
  mockAuthedFetch("tutor");
  renderApp("/tutor/submissions/3");
  const sidebar = await screen.findByRole("navigation", { name: "Tutor navigation" });
  expect(within(sidebar).getByRole("link", { name: "Mark" })).toHaveAttribute(
    "aria-current",
    "true",
  );
});

test("the Library lists only teaching material, not setup, readiness or papers", async () => {
  mockAuthedFetch("tutor");
  renderApp("/tutor/library");
  // Its three sections, and a pointer to where syllabuses went — not a card.
  expect(await screen.findByRole("heading", { level: 2, name: "Classifieds" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { level: 2, name: "Files" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { level: 2, name: "Recordings" })).toBeInTheDocument();
  expect(
    within(screen.getByRole("main")).getByRole("link", { name: "Subject setup" }),
  ).toHaveAttribute("href", "/tutor/subject-setup#syllabus");
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

test("Settings keeps only the messages and the account", async () => {
  mockAuthedFetch("tutor");
  renderApp("/tutor/settings");
  await screen.findByRole("heading", { level: 1, name: "Settings" });
  expect(screen.getAllByRole("region").map((r) => r.id)).toEqual(["messages", "account"]);
  const index = screen.getByRole("navigation", { name: "Settings sections" });
  expect(within(index).getAllByRole("link")).toHaveLength(2);
});

test("the old Syllabuses URL lands on Subject setup at its Syllabus section", async () => {
  mockAuthedFetch("tutor");
  renderApp("/tutor/syllabuses");
  expect(
    await screen.findByRole("heading", { level: 1, name: "Subject setup" }),
  ).toBeInTheDocument();
  await waitFor(() => expect(document.activeElement?.id).toBe("syllabus"));
});

test("the retired Today URL still lands on Today", async () => {
  mockAuthedFetch("tutor");
  renderApp("/tutor/today");
  const sidebar = await screen.findByRole("navigation", { name: "Tutor navigation" });
  const today = within(sidebar).getByRole("link", { name: "Today" });
  await waitFor(() => expect(today).toHaveAttribute("aria-current", "page"));
});

test("an assignment page lights Classes, and a student page lights Students only", async () => {
  mockAuthedFetch("tutor");
  const first = renderApp("/tutor/assignments/5");
  let sidebar = await screen.findByRole("navigation", { name: "Tutor navigation" });
  expect(within(sidebar).getByRole("link", { name: "Classes" })).toHaveAttribute(
    "aria-current",
    "true",
  );
  first.unmount();

  mockAuthedFetch("tutor");
  renderApp("/tutor/students/9");
  sidebar = await screen.findByRole("navigation", { name: "Tutor navigation" });
  expect(within(sidebar).getByRole("link", { name: "Students" })).toHaveAttribute(
    "aria-current",
    "true",
  );
  expect(within(sidebar).getByRole("link", { name: "Classes" })).not.toHaveAttribute(
    "aria-current",
  );
});

test("a class's own Students tab lights Classes, not Students", async () => {
  mockAuthedFetch("tutor");
  renderApp("/tutor/groups/3/students");
  const sidebar = await screen.findByRole("navigation", { name: "Tutor navigation" });
  expect(within(sidebar).getByRole("link", { name: "Classes" })).toHaveAttribute(
    "aria-current",
    "true",
  );
  expect(within(sidebar).getByRole("link", { name: "Students" })).not.toHaveAttribute(
    "aria-current",
  );
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
  const menu = await screen.findByRole("group", { name: "More" });
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

test("the tutor More sheet holds the two destinations that do not fit the bar", async () => {
  mockAuthedFetch("tutor");
  renderApp("/tutor");
  const tabBar = await screen.findByRole("navigation", { name: "Tutor tabs" });
  fireEvent.click(within(tabBar).getByRole("button", { name: /More/ }));
  const menu = await screen.findByRole("group", { name: "More" });
  for (const label of ["Mocks", "Library"]) {
    expect(within(menu).getByText(label)).toBeInTheDocument();
  }
  expect(within(tabBar).getByText("Today")).toBeInTheDocument();
});

test("a nested route sets aria-current on its parent destination", async () => {
  mockAuthedFetch("tutor");
  renderApp("/tutor/groups/3/homework");
  const sidebar = await screen.findByRole("navigation", { name: "Tutor navigation" });
  const classes = within(sidebar).getByRole("link", { name: "Classes" });
  await waitFor(() => expect(classes).toHaveAttribute("aria-current", "true"));
  expect(within(sidebar).getByRole("link", { name: "Library" })).not.toHaveAttribute(
    "aria-current",
  );
  expect(within(sidebar).getByRole("link", { name: "Today" })).not.toHaveAttribute("aria-current");
});

test("the More button lights while the page is one of its destinations", async () => {
  mockAuthedFetch("tutor");
  renderApp("/tutor/library");
  const tabBar = await screen.findByRole("navigation", { name: "Tutor tabs" });
  const more = within(tabBar).getByRole("button", { name: /More/ });
  expect(more.className).toContain("text-brand-600");
  fireEvent.click(more);
  const menu = await screen.findByRole("group", { name: "More" });
  expect(within(menu).getByRole("link", { name: "Library" })).toHaveAttribute(
    "aria-current",
    "page",
  );
});

test("the section index moves focus to the section it names", async () => {
  mockAuthedFetch("tutor");
  renderApp("/tutor/settings");
  const index = await screen.findByRole("navigation", { name: "Settings sections" });
  fireEvent.click(within(index).getByRole("link", { name: "Account and integrations" }));
  await waitFor(() => expect(document.activeElement?.id).toBe("account"));
});

test("Escape closes the More sheet and returns focus to its button", async () => {
  mockAuthedFetch("tutor");
  renderApp("/tutor");
  const tabBar = await screen.findByRole("navigation", { name: "Tutor tabs" });
  const more = within(tabBar).getByRole("button", { name: /More/ });
  fireEvent.click(more);
  await screen.findByRole("group", { name: "More" });
  fireEvent.keyDown(document, { key: "Escape" });
  await waitFor(() =>
    expect(screen.queryByRole("group", { name: "More" })).not.toBeInTheDocument(),
  );
  expect(more).toHaveFocus();
  expect(more).toHaveAttribute("aria-expanded", "false");
});

test("choosing an item closes the More sheet", async () => {
  mockAuthedFetch("tutor");
  renderApp("/tutor");
  const tabBar = await screen.findByRole("navigation", { name: "Tutor tabs" });
  fireEvent.click(within(tabBar).getByRole("button", { name: /More/ }));
  fireEvent.click(
    within(await screen.findByRole("group", { name: "More" })).getByRole("link", {
      name: "Library",
    }),
  );
  await waitFor(() =>
    expect(screen.queryByRole("group", { name: "More" })).not.toBeInTheDocument(),
  );
});

test("the More button names the current page for a screen reader, and the sheet scrolls", async () => {
  mockAuthedFetch("tutor");
  renderApp("/tutor/mocks");
  const tabBar = await screen.findByRole("navigation", { name: "Tutor tabs" });
  const more = within(tabBar).getByRole("button", { name: /^More\s*,\s*current page: Mocks$/ });
  // The visible label is unchanged.
  expect(more.textContent).toContain("More");
  fireEvent.click(more);
  const menu = await screen.findByRole("group", { name: "More" });
  expect(menu.className).toContain("overflow-y-auto");
  expect(menu.className).toContain("max-h-");
});

test("More says nothing extra when the page is not inside it", async () => {
  mockAuthedFetch("tutor");
  renderApp("/tutor");
  const tabBar = await screen.findByRole("navigation", { name: "Tutor tabs" });
  expect(within(tabBar).getByRole("button", { name: "More" })).toBeInTheDocument();
});

test("a setup page keeps Subject setup lit in the name menu", async () => {
  mockAuthedFetch("tutor");
  renderApp("/tutor/subject-setup");
  fireEvent.click((await screen.findAllByRole("button", { name: /Demo User/ }))[0]);
  expect(await screen.findByRole("menuitem", { name: "Subject setup" })).toHaveAttribute(
    "aria-current",
    "page",
  );
});

test("Mocks lights on its own page only", async () => {
  mockAuthedFetch("tutor");
  renderApp("/tutor/mocks");
  const sidebar = await screen.findByRole("navigation", { name: "Tutor navigation" });
  const mocks = within(sidebar).getByRole("link", { name: "Mocks" });
  await waitFor(() => expect(mocks).toHaveAttribute("aria-current", "page"));
  expect(within(sidebar).getByRole("link", { name: "Classes" })).not.toHaveAttribute(
    "aria-current",
  );
});
