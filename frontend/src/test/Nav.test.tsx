import { render, screen } from "@testing-library/react";
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

test("student sees all 8 student tabs", async () => {
  mockAuthedFetch("student");
  renderApp("/student");
  for (const label of [
    "Home",
    "Readiness",
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

test("tutor sees all 9 tutor tabs", async () => {
  mockAuthedFetch("tutor");
  renderApp("/tutor");
  for (const label of [
    "Today",
    "Classes",
    "Class readiness",
    "Homework",
    "Past papers",
    "Mocks",
    "Syllabuses",
    "Preferences",
    "Settings",
  ]) {
    await expectNavLabel(label);
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
