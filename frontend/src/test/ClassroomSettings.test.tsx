import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import ClassroomSettingsPage from "../tutor/ClassroomSettingsPage";

function mockFetch(status: Record<string, unknown>) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/classroom/status")) {
        return new Response(JSON.stringify(status), { status: 200 });
      }
      return new Response(JSON.stringify([]), { status: 200 });
    }),
  );
}

function renderPage() {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <ClassroomSettingsPage />
      </MemoryRouter>
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

test("offers to connect when Google is configured but not linked", async () => {
  mockFetch({ configured: true, connected: false, google_email: null, connected_at: null });
  renderPage();
  expect(await screen.findByText("Connect Google Classroom")).toBeInTheDocument();
});

test("shows the connected account, sync and unlink controls", async () => {
  mockFetch({
    configured: true,
    connected: true,
    google_email: "tutor@school.org",
    connected_at: "2026-07-01T00:00:00Z",
  });
  renderPage();
  expect(await screen.findByText(/tutor@school.org/)).toBeInTheDocument();
  expect(screen.getByText("Sync now")).toBeInTheDocument();
  expect(screen.getByText("Linked classes")).toBeInTheDocument();
});

test("explains itself instead of offering a dead button when unconfigured", async () => {
  mockFetch({ configured: false, connected: false, google_email: null, connected_at: null });
  renderPage();
  expect(await screen.findByText(/isn't set up on this deployment/)).toBeInTheDocument();
  expect(screen.queryByText("Connect Google Classroom")).not.toBeInTheDocument();
});
