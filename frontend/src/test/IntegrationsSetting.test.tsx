import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, test, vi } from "vitest";
import IntegrationsSetting from "../tutor/IntegrationsSetting";

/* Task 7.3: connecting Zoom and Google Meet. Until the owner registers the apps
   each provider reads "not set up yet" and cannot be started. */

const NOTE =
  "Meet attendance needs a paid Google Workspace account — a free Google account returns no attendance.";

function stub(items: object[]) {
  const calls: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      calls.push(`${(init?.method ?? "GET").toUpperCase()} ${url}`);
      if (url.endsWith("/authorize-url")) {
        return new Response(
          JSON.stringify({ url: "https://zoom.us/oauth/authorize?x=1", state: "s1" }),
          {
            status: 200,
          },
        );
      }
      if (init?.method === "DELETE") return new Response(null, { status: 204 });
      return new Response(JSON.stringify(items), { status: 200 });
    }),
  );
  return calls;
}

function renderIt() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <IntegrationsSetting />
    </QueryClientProvider>,
  );
}

const base = { account_email: null, connected_at: null };

afterEach(() => {
  vi.unstubAllGlobals();
  sessionStorage.clear();
});

test("providers that are not configured say so and cannot be connected", async () => {
  stub([
    { ...base, provider: "zoom", configured: false, connected: false, note: "Zoom note." },
    { ...base, provider: "google_meet", configured: false, connected: false, note: NOTE },
  ]);
  renderIt();
  expect(await screen.findAllByText(/Not set up for Avora yet/)).toHaveLength(2);
  expect(screen.getByRole("button", { name: "Connect Zoom" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Connect Google Meet" })).toBeDisabled();
  // The Workspace requirement is stated before anyone connects.
  expect(screen.getByText(/needs a paid Google Workspace account/)).toBeInTheDocument();
});

test("connecting stashes the state and sends the browser to the provider", async () => {
  const assign = vi.fn();
  vi.stubGlobal("location", { ...window.location, assign });
  stub([
    { ...base, provider: "zoom", configured: true, connected: false, note: "" },
    { ...base, provider: "google_meet", configured: true, connected: false, note: NOTE },
  ]);
  renderIt();
  fireEvent.click(await screen.findByRole("button", { name: "Connect Zoom" }));
  await waitFor(() => expect(assign).toHaveBeenCalledWith("https://zoom.us/oauth/authorize?x=1"));
  expect(sessionStorage.getItem("avora-integration-state-zoom")).toBe("s1");
});

test("a connected provider shows the account and can be disconnected", async () => {
  const calls = stub([
    {
      provider: "zoom",
      configured: true,
      connected: true,
      account_email: "host@school.example",
      connected_at: null,
      note: "",
    },
  ]);
  renderIt();
  expect(await screen.findByText(/Connected as host@school.example/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Disconnect Zoom" }));
  await waitFor(() => expect(calls).toContain("DELETE /api/v1/integrations/zoom"));
});
