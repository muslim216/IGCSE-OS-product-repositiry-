import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import SettingsPage from "../tutor/SettingsPage";

/**
 * Replaces ClassroomSettings.test.tsx, whose subject — ClassroomSettingsPage —
 * was removed with the Classroom surface (AV-58). Its three assertions were
 * all about Google connect/sync/unlink controls that no longer render
 * anywhere, so there was nothing to repoint them at.
 *
 * What did survive is the route: /tutor/settings is still linked from the
 * Library, and after the Classroom block came out the timezone control is the
 * only thing left on it. Nothing covered that control before — the old file
 * rendered it incidentally and never asserted on it — so without this the
 * page would go from three tests to none.
 */

function mockFetch(organization: Record<string, unknown>) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/organization")) {
        return new Response(JSON.stringify(organization), { status: 200 });
      }
      return new Response(JSON.stringify([]), { status: 200 });
    }),
  );
}

function renderPage() {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <SettingsPage />
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

test("shows the organization's time zone", async () => {
  mockFetch({ id: 1, name: "Test Org", timezone: "Asia/Qatar" });
  renderPage();
  // Matched through the sentence rather than the bare zone name: the picker
  // lists every IANA zone this browser knows, so "Asia/Qatar" on its own also
  // matches an <option> and is ambiguous.
  const current = await screen.findByText(/^Currently/);
  expect(current).toHaveTextContent("Currently Asia/Qatar.");
});

test("states the UTC fallback rather than implying it when unset", async () => {
  // PROD-2: absent is shown as absent. A tutor whose lesson list is a day out
  // has to be able to read why, which a silent default hides.
  mockFetch({ id: 1, name: "Test Org", timezone: null });
  renderPage();
  expect(await screen.findByText(/Not set — days are worked out in UTC/)).toBeInTheDocument();
});

test("offers no Google Classroom controls", async () => {
  // The point of the file. AV-58 hid Classroom; if a later change re-adds a
  // connect button here, that is a product decision and should fail a test
  // rather than pass silently.
  mockFetch({ id: 1, name: "Test Org", timezone: "Asia/Qatar" });
  renderPage();
  expect(await screen.findByText("Time zone")).toBeInTheDocument();
  expect(screen.queryByText(/Google Classroom/)).not.toBeInTheDocument();
  expect(screen.queryByText("Sync now")).not.toBeInTheDocument();
  expect(screen.queryByText("Linked classes")).not.toBeInTheDocument();
});
