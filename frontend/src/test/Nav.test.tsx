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

test("the tutor nav has twelve destinations, in the owner's order", async () => {
  mockAuthedFetch("tutor");
  renderApp("/tutor");
  const sidebar = await screen.findByRole("navigation", { name: "Tutor navigation" });
  const labels = within(sidebar)
    .getAllByRole("link")
    .map((link) => link.textContent);
  expect(labels).toEqual([
    "Overview",
    "Review",
    "Homework",
    "Classes",
    "Students",
    "Mocks",
    "Past papers",
    "Readiness",
    "Reports",
    "Library",
    "Subject setup",
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

test("the retired Papers & mocks hub URL lands on Past papers", async () => {
  mockAuthedFetch("tutor");
  renderApp("/tutor/papers");
  expect(await screen.findByRole("heading", { level: 1, name: "Past papers" })).toBeInTheDocument();
  const main = screen.getByRole("main");
  expect(within(main).queryByText("Papers & mocks")).not.toBeInTheDocument();
});

test("Booklets and Mocks are top-level pages: no back link to the retired hub", async () => {
  mockAuthedFetch("tutor");
  const view = renderApp("/tutor/booklets");
  await screen.findByRole("heading", { level: 1 });
  const main = screen.getByRole("main");
  expect(within(main).getByRole("link", { name: /Past papers/ })).toHaveAttribute(
    "href",
    "/tutor/past-papers",
  );
  view.unmount();

  mockAuthedFetch("tutor");
  renderApp("/tutor/mocks");
  await screen.findByRole("heading", { level: 1 });
  expect(within(screen.getByRole("main")).queryByText("Papers & mocks")).not.toBeInTheDocument();
});

test("a submission page keeps Review lit", async () => {
  mockAuthedFetch("tutor");
  renderApp("/tutor/submissions/3");
  const sidebar = await screen.findByRole("navigation", { name: "Tutor navigation" });
  expect(within(sidebar).getByRole("link", { name: "Review" })).toHaveAttribute(
    "aria-current",
    "page",
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

test("an old setup URL keeps Subject setup lit", async () => {
  mockAuthedFetch("tutor");
  renderApp("/tutor/syllabuses");
  const sidebar = await screen.findByRole("navigation", { name: "Tutor navigation" });
  const setup = within(sidebar).getByRole("link", { name: "Subject setup" });
  await waitFor(() => expect(setup.className).toContain("bg-brand-600"));
  expect(within(sidebar).getByRole("link", { name: "Library" }).className).not.toContain(
    "bg-brand-600",
  );
  expect(within(sidebar).getByRole("link", { name: "Past papers" }).className).not.toContain(
    "bg-brand-600",
  );
});

test("a past paper page highlights Past papers", async () => {
  mockAuthedFetch("tutor");
  renderApp("/tutor/past-papers");
  const sidebar = await screen.findByRole("navigation", { name: "Tutor navigation" });
  const link = within(sidebar).getByRole("link", { name: "Past papers" });
  await waitFor(() => expect(link.className).toContain("bg-brand-600"));
  expect(within(sidebar).getByRole("link", { name: "Library" }).className).not.toContain(
    "bg-brand-600",
  );
});

test("the retired Today URL still lands on Overview", async () => {
  mockAuthedFetch("tutor");
  renderApp("/tutor/today");
  const sidebar = await screen.findByRole("navigation", { name: "Tutor navigation" });
  const overview = within(sidebar).getByRole("link", { name: "Overview" });
  await waitFor(() => expect(overview).toHaveAttribute("aria-current", "page"));
});

test("the old Papers & mocks hub and Booklets URLs keep Past papers lit", async () => {
  for (const url of ["/tutor/papers", "/tutor/booklets"]) {
    mockAuthedFetch("tutor");
    const view = renderApp(url);
    const sidebar = await screen.findByRole("navigation", { name: "Tutor navigation" });
    const link = within(sidebar).getByRole("link", { name: "Past papers" });
    await waitFor(() => expect(link).toHaveAttribute("aria-current", "page"));
    expect(within(sidebar).getByRole("link", { name: "Mocks" })).not.toHaveAttribute(
      "aria-current",
    );
    view.unmount();
  }
});

test("Mocks lights on its own page and not Past papers", async () => {
  mockAuthedFetch("tutor");
  renderApp("/tutor/mocks");
  const sidebar = await screen.findByRole("navigation", { name: "Tutor navigation" });
  const mocks = within(sidebar).getByRole("link", { name: "Mocks" });
  await waitFor(() => expect(mocks).toHaveAttribute("aria-current", "page"));
  expect(within(sidebar).getByRole("link", { name: "Past papers" })).not.toHaveAttribute(
    "aria-current",
  );
});

test("Homework is its own page and stays lit on an assignment", async () => {
  mockAuthedFetch("tutor");
  renderApp("/tutor/homework");
  expect(await screen.findByRole("heading", { level: 1, name: "Homework" })).toBeInTheDocument();
  const sidebar = screen.getByRole("navigation", { name: "Tutor navigation" });
  expect(within(sidebar).getByRole("link", { name: "Homework" })).toHaveAttribute(
    "aria-current",
    "page",
  );
  expect(within(sidebar).getByRole("link", { name: "Review" })).not.toHaveAttribute("aria-current");
});

test("an assignment page lights Homework, and a student page lights Students only", async () => {
  mockAuthedFetch("tutor");
  const first = renderApp("/tutor/assignments/5");
  let sidebar = await screen.findByRole("navigation", { name: "Tutor navigation" });
  expect(within(sidebar).getByRole("link", { name: "Homework" })).toHaveAttribute(
    "aria-current",
    "page",
  );
  first.unmount();

  mockAuthedFetch("tutor");
  renderApp("/tutor/students/9");
  sidebar = await screen.findByRole("navigation", { name: "Tutor navigation" });
  expect(within(sidebar).getByRole("link", { name: "Students" })).toHaveAttribute(
    "aria-current",
    "page",
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
    "page",
  );
  expect(within(sidebar).getByRole("link", { name: "Students" })).not.toHaveAttribute(
    "aria-current",
  );
});

test("the Past papers page links to Booklets", async () => {
  mockAuthedFetch("tutor");
  renderApp("/tutor/past-papers");
  const link = await screen.findByRole("link", { name: "Split it with Booklets" });
  expect(link).toHaveAttribute("href", "/tutor/booklets");
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
  await screen.findAllByText("Overview");
  expect(screen.queryByText("AI Guidance")).not.toBeInTheDocument();
});

test("the tutor More sheet holds the destinations that do not fit the bar", async () => {
  mockAuthedFetch("tutor");
  renderApp("/tutor");
  const tabBar = await screen.findByRole("navigation", { name: "Tutor tabs" });
  fireEvent.click(within(tabBar).getByRole("button", { name: /More/ }));
  const menu = await screen.findByRole("menu");
  // Twelve destinations: three tabs plus More, so nine fold into the sheet and
  // none is lost on a phone.
  for (const label of [
    "Classes",
    "Students",
    "Mocks",
    "Past papers",
    "Readiness",
    "Reports",
    "Library",
    "Subject setup",
    "Settings",
  ]) {
    expect(within(menu).getByText(label)).toBeInTheDocument();
  }
  expect(within(tabBar).getByText("Overview")).toBeInTheDocument();
});

test("a nested route sets aria-current on its parent destination", async () => {
  mockAuthedFetch("tutor");
  renderApp("/tutor/past-papers");
  const sidebar = await screen.findByRole("navigation", { name: "Tutor navigation" });
  const papers = within(sidebar).getByRole("link", { name: "Past papers" });
  await waitFor(() => expect(papers).toHaveAttribute("aria-current", "page"));
  expect(within(sidebar).getByRole("link", { name: "Library" })).not.toHaveAttribute(
    "aria-current",
  );
  expect(within(sidebar).getByRole("link", { name: "Overview" })).not.toHaveAttribute(
    "aria-current",
  );
});

test("the More button lights while the page is one of its destinations", async () => {
  mockAuthedFetch("tutor");
  renderApp("/tutor/settings");
  const tabBar = await screen.findByRole("navigation", { name: "Tutor tabs" });
  const more = within(tabBar).getByRole("button", { name: /More/ });
  expect(more.className).toContain("text-brand-600");
  fireEvent.click(more);
  const menu = await screen.findByRole("menu");
  expect(within(menu).getByRole("menuitem", { name: "Settings" })).toHaveAttribute(
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
  await screen.findByRole("menu");
  fireEvent.keyDown(document, { key: "Escape" });
  await waitFor(() => expect(screen.queryByRole("menu")).not.toBeInTheDocument());
  expect(more).toHaveFocus();
  expect(more).toHaveAttribute("aria-expanded", "false");
});

test("choosing an item closes the More sheet", async () => {
  mockAuthedFetch("tutor");
  renderApp("/tutor");
  const tabBar = await screen.findByRole("navigation", { name: "Tutor tabs" });
  fireEvent.click(within(tabBar).getByRole("button", { name: /More/ }));
  fireEvent.click(
    within(await screen.findByRole("menu")).getByRole("menuitem", { name: "Library" }),
  );
  await waitFor(() => expect(screen.queryByRole("menu")).not.toBeInTheDocument());
});

test("the More button names the current page for a screen reader, and the sheet scrolls", async () => {
  mockAuthedFetch("tutor");
  renderApp("/tutor/classes");
  const tabBar = await screen.findByRole("navigation", { name: "Tutor tabs" });
  const more = within(tabBar).getByRole("button", { name: /^More\s*,\s*current page: Classes$/ });
  // The visible label is unchanged.
  expect(more.textContent).toContain("More");
  fireEvent.click(more);
  const menu = await screen.findByRole("menu");
  expect(menu.className).toContain("overflow-y-auto");
  expect(menu.className).toContain("max-h-");
});

test("More says nothing extra when the page is not inside it", async () => {
  mockAuthedFetch("tutor");
  renderApp("/tutor");
  const tabBar = await screen.findByRole("navigation", { name: "Tutor tabs" });
  expect(within(tabBar).getByRole("button", { name: "More" })).toBeInTheDocument();
});
