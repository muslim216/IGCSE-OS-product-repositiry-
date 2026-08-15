import { fireEvent, render, screen, within } from "@testing-library/react";
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
  localStorage.setItem(
    "igcse-os-tokens",
    JSON.stringify({ access_token: "t", refresh_token: "r", token_type: "bearer" }),
  );
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
    // reader gets, not for the engine behind one of its numbers. Improvement is
    // its own destination and appears on no home surface.
    "Progress",
    "Improvement",
    "Files",
    "Recordings",
    "Homework",
    "AI Tutor",
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

test("the tutor primary nav has exactly four items", async () => {
  mockAuthedFetch("tutor");
  renderApp("/tutor");
  const sidebar = await screen.findByRole("navigation", { name: "Tutor navigation" });
  for (const label of ["Today", "Classes", "Review", "Library"]) {
    expect(within(sidebar).getByText(label)).toBeInTheDocument();
  }
  // The six that moved onto the Library shelf are gone from the primary nav.
  for (const label of ["Class readiness", "Homework", "Past papers", "Mocks", "Syllabuses"]) {
    expect(within(sidebar).queryByText(label)).not.toBeInTheDocument();
  }
});

test("the Library shelf links to every destination that left the nav", async () => {
  mockAuthedFetch("tutor");
  renderApp("/tutor/library");
  for (const label of [
    "Past papers",
    "Mocks",
    "Syllabuses",
    "Class readiness",
    "Preferences",
    "Settings",
  ]) {
    expect(await screen.findByText(label)).toBeInTheDocument();
  }
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

test("the mobile tab bar shows main-slot destinations, not the bottom-slot one", async () => {
  // The bottom-slot "AI Tutor" sits apart from the workflow nav, so it must not
  // become a primary thumb tab — it folds into More instead. The always-visible
  // bar carries the main-workflow items.
  mockAuthedFetch("student");
  renderApp("/student");
  const tabBar = await screen.findByRole("navigation", { name: "Student tabs" });
  expect(within(tabBar).getByText("Home")).toBeInTheDocument();
  expect(within(tabBar).queryByText("AI Tutor")).not.toBeInTheDocument();
  // Overflow exists because the student has more destinations than the bar holds.
  expect(within(tabBar).getByRole("button", { name: /More/ })).toBeInTheDocument();
});

test("every nav destination remains reachable on mobile via More", async () => {
  mockAuthedFetch("student");
  renderApp("/student");
  const tabBar = await screen.findByRole("navigation", { name: "Student tabs" });
  fireEvent.click(within(tabBar).getByRole("button", { name: /More/ }));
  const menu = await screen.findByRole("menu");
  // The destinations that don't fit the bar — including the bottom-slot item —
  // are all present in the overflow sheet.
  for (const label of ["Exams", "Files", "Recordings", "AI Tutor"]) {
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
