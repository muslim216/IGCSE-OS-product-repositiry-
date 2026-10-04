import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, test, vi } from "vitest";
import OnlineAttendance from "../tutor/OnlineAttendance";

/* Task 7.3: an online lesson's attendance. Unmatched participants are listed for
   the tutor to resolve; a provider that is not set up says so instead of erroring. */

type Calls = { method: string; url: string; body: unknown }[];

function stub(opts: { meeting?: object; integrations?: object[]; register?: object[] }): Calls {
  const calls: Calls = [];
  const meeting = {
    provider: "zoom",
    link: "https://zoom.us/j/81234567890",
    last_import: null,
    participants: [],
    ...opts.meeting,
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = (init?.method ?? "GET").toUpperCase();
      calls.push({ method, url, body: init?.body ? JSON.parse(String(init.body)) : null });
      if (url.endsWith("/meeting")) return new Response(JSON.stringify(meeting), { status: 200 });
      if (url.endsWith("/api/v1/integrations")) {
        return new Response(
          JSON.stringify(
            opts.integrations ?? [
              {
                provider: "zoom",
                configured: true,
                connected: true,
                account_email: null,
                connected_at: null,
                note: "",
              },
            ],
          ),
          { status: 200 },
        );
      }
      if (url.includes("/resolve")) {
        return new Response(JSON.stringify({ id: 5, resolved: true }), { status: 200 });
      }
      if (url.endsWith("/attendance")) {
        return new Response(JSON.stringify(opts.register ?? []), { status: 200 });
      }
      return new Response("{}", { status: 200 });
    }),
  );
  return calls;
}

function renderIt() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <OnlineAttendance lessonId={9} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

const register = [
  { student_id: 11, name: "Sara", state: "present", source: "zoom", recorded_at: null },
  { student_id: 12, name: "Omar", state: "absent", source: "zoom", recorded_at: null },
  { student_id: 13, name: "Lina", state: null, source: null, recorded_at: null },
];

test("unmatched participants are listed and picking a student resolves them", async () => {
  const calls = stub({
    register,
    meeting: {
      last_import: {
        status: "succeeded",
        error_code: null,
        message: "1 present.",
        finished_at: null,
      },
      participants: [
        {
          id: 5,
          display_name: "S. A.",
          email: null,
          duration_seconds: 1200,
          matched_student_id: null,
          resolved: false,
        },
        {
          id: 6,
          display_name: "Sara",
          email: "sara@example.com",
          duration_seconds: 60,
          matched_student_id: 11,
          resolved: false,
        },
      ],
    },
  });
  renderIt();

  expect(await screen.findByText("Not matched to a student")).toBeInTheDocument();
  expect(screen.getByText("S. A.")).toBeInTheDocument();
  expect(screen.getByText(/No email shared · 20 min/)).toBeInTheDocument();
  // Matched people are not asked about.
  expect(screen.queryByLabelText("This is… (Sara)")).not.toBeInTheDocument();
  // The register says where each mark came from, and stays editable.
  expect(screen.getAllByText("from Zoom")).toHaveLength(2);
  expect(screen.getByText("Not taken")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Present: Sara" })).toBeInTheDocument();

  fireEvent.change(await screen.findByLabelText("This is… (S. A.)"), { target: { value: "13" } });
  await waitFor(() =>
    expect(calls.find((c) => c.url.endsWith("/participants/5/resolve"))).toMatchObject({
      method: "POST",
      body: { student_id: 13 },
    }),
  );
});

test("a provider that is not set up says so rather than offering an import", async () => {
  stub({
    register,
    integrations: [
      {
        provider: "zoom",
        configured: false,
        connected: false,
        account_email: null,
        connected_at: null,
        note: "",
      },
    ],
  });
  renderIt();
  expect(await screen.findByText(/Zoom attendance isn't set up for Avora yet/)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Import attendance" })).not.toBeInTheDocument();
});

test("a configured but unconnected provider points at Settings", async () => {
  stub({
    register,
    integrations: [
      {
        provider: "zoom",
        configured: true,
        connected: false,
        account_email: null,
        connected_at: null,
        note: "",
      },
    ],
  });
  renderIt();
  expect(await screen.findByRole("link", { name: "Connect Zoom" })).toHaveAttribute(
    "href",
    "/tutor/settings",
  );
  expect(screen.queryByRole("button", { name: "Import attendance" })).not.toBeInTheDocument();
});

test("a failed import shows its reason, and Import queues one", async () => {
  const calls = stub({
    register,
    meeting: {
      last_import: {
        status: "failed",
        error_code: "no_data",
        message: "Google returned no attendance.",
        finished_at: null,
      },
    },
  });
  renderIt();
  expect(
    await screen.findByText(/Couldn't import attendance\. Google returned no attendance\./),
  ).toBeInTheDocument();
  fireEvent.click(await screen.findByRole("button", { name: "Import attendance" }));
  await waitFor(() =>
    expect(calls.some((c) => c.method === "POST" && c.url.endsWith("/attendance/import"))).toBe(
      true,
    ),
  );
});

test("an online lesson with no link asks for one", async () => {
  stub({ register, meeting: { provider: null, link: null } });
  renderIt();
  expect(
    await screen.findByLabelText("Add the Zoom or Google Meet link to import attendance"),
  ).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Import attendance" })).not.toBeInTheDocument();
});
