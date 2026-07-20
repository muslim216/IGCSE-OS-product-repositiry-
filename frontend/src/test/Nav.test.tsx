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

test("student sees all 6 student tabs", async () => {
  mockAuthedFetch("student");
  renderApp("/student");
  expect(await screen.findByText("Readiness")).toBeInTheDocument();
  for (const label of ["Files", "Recordings", "Homework", "AI Tutor", "Exams"]) {
    expect(screen.getByText(label)).toBeInTheDocument();
  }
});

test("tutor sees all 6 tutor tabs", async () => {
  mockAuthedFetch("tutor");
  renderApp("/tutor");
  expect(await screen.findByText("Classes")).toBeInTheDocument();
  for (const label of ["Class readiness", "Homework", "Preferences", "Mocks", "Today"]) {
    expect(screen.getByText(label)).toBeInTheDocument();
  }
});
