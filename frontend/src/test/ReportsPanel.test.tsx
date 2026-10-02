import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, test, vi } from "vitest";
import { ReportsPanel } from "../components/ReportsPanel";

/* The reports panel is shared by all three roles. What it must never do: show
   a raw enum ("student report", "failed") or a stored diagnostic as if it were
   a sentence for the reader. */

const FAILED = {
  id: 4,
  student_id: 2,
  subject_id: null,
  audience: "student",
  status: "failed",
  title: "Progress report — September",
  created_at: "2026-09-20T10:00:00Z",
  generated_at: null,
};

function stub(reports: unknown[]) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), "http://localhost");
      const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200 });
      if (url.pathname === "/api/v1/reports") return json(reports);
      if (url.pathname === "/api/v1/reports/4") {
        return json({ ...FAILED, content: null, error: "anthropic 529 overloaded_error" });
      }
      return json([]);
    }),
  );
}

function renderPanel(props: Partial<Parameters<typeof ReportsPanel>[0]> = {}) {
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <ReportsPanel studentId={2} audiences={["student", "tutor", "parent"]} {...props} />
    </QueryClientProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

test("audience options read as sentence-case names, not raw values", async () => {
  stub([]);
  renderPanel();
  const select = await screen.findByLabelText("Who the report is for");
  const labels = [...select.querySelectorAll("option")].map((o) => o.textContent);
  expect(labels).toEqual(["Student report", "Tutor report", "Parent report"]);
});

test("a failed report says so in words and never shows the stored error", async () => {
  stub([FAILED]);
  renderPanel();
  expect(await screen.findByText("Couldn't be written")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /Progress report — September/ }));
  expect(await screen.findByText(/This report couldn't be written/)).toBeInTheDocument();
  expect(screen.queryByText(/overloaded/)).not.toBeInTheDocument();
});

test("a list that fails to load can be retried from where the failure is shown", async () => {
  // The message used to end "Try again." with nothing on screen to try it with.
  let listCalls = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), "http://localhost");
      if (url.pathname === "/api/v1/reports" && listCalls++ === 0) {
        return new Response(JSON.stringify({ detail: "boom" }), { status: 500 });
      }
      return new Response(JSON.stringify([]), { status: 200 });
    }),
  );
  renderPanel();
  const failure = await screen.findByRole("alert");
  expect(failure).toHaveTextContent("Reports didn't load");
  fireEvent.click(within(failure).getByRole("button", { name: "Try again" }));
  expect(await screen.findByText("No reports yet")).toBeInTheDocument();
});

test("a report that fails to open can be retried", async () => {
  let openCalls = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), "http://localhost");
      const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200 });
      if (url.pathname === "/api/v1/reports") return json([{ ...FAILED, status: "ready" }]);
      if (url.pathname === "/api/v1/reports/4") {
        if (openCalls++ === 0) {
          return new Response(JSON.stringify({ detail: "boom" }), { status: 500 });
        }
        return json({ ...FAILED, status: "ready", content: "Steady progress in algebra." });
      }
      return json([]);
    }),
  );
  renderPanel();
  fireEvent.click(await screen.findByRole("button", { name: /Progress report — September/ }));
  const failure = await screen.findByRole("alert");
  expect(failure).toHaveTextContent("This report didn't open");
  fireEvent.click(within(failure).getByRole("button", { name: "Try again" }));
  expect(await screen.findByText("Steady progress in algebra.")).toBeInTheDocument();
});

test("a reader who cannot generate is told where reports come from", async () => {
  stub([]);
  renderPanel({ audiences: ["student"], canGenerate: false });
  expect(await screen.findByText("No reports yet")).toBeInTheDocument();
  expect(screen.getByText(/Your tutor writes these/)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /generate/i })).not.toBeInTheDocument();
});

/* `POST /reports/generate` answers 409 with a plain sentence when there is
   nothing to report. The panel used to swallow it: the button re-enabled and
   the tutor was told nothing. */

const NOTHING = "This student isn't in a class yet, so there is nothing to report.";

const GENERATING = {
  id: 7,
  student_id: 2,
  subject_id: null,
  audience: "tutor",
  status: "generating",
  title: "Tutor report",
  created_at: "2026-10-01T10:00:00Z",
  generated_at: null,
  content: null,
  error: null,
};

/** Each POST consumes the next queued outcome. A successful one is kept, so
    the `/reports` list returns it afterwards, as the API does. */
function stubGenerate(posts: ("conflict" | "ok")[]) {
  const generated: (typeof GENERATING)[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = new URL(String(input), "http://localhost").pathname;
      if ((init?.method ?? "GET").toUpperCase() === "POST") {
        if (posts.shift() === "conflict")
          return new Response(JSON.stringify({ detail: NOTHING }), { status: 409 });
        generated.push(GENERATING);
        return new Response(JSON.stringify(GENERATING), { status: 200 });
      }
      return new Response(JSON.stringify(path.endsWith("/reports") ? generated : GENERATING), {
        status: 200,
      });
    }),
  );
}

test("a 409 from generate shows the server's sentence in an alert", async () => {
  stubGenerate(["conflict"]);
  renderPanel({ audiences: ["tutor"] });

  fireEvent.click(await screen.findByRole("button", { name: "Generate report" }));

  expect(await screen.findByRole("alert")).toHaveTextContent(NOTHING);
  expect(screen.getByRole("button", { name: "Generate report" })).toBeEnabled();
});

test("a later successful generate clears the alert", async () => {
  stubGenerate(["conflict", "ok"]);
  renderPanel({ audiences: ["tutor"] });

  fireEvent.click(await screen.findByRole("button", { name: "Generate report" }));
  await screen.findByRole("alert");

  fireEvent.click(screen.getByRole("button", { name: "Generate report" }));

  expect(await screen.findByText(/Writing the report…/)).toBeInTheDocument();
  await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
  // The list refetches and now holds the report that was just generated.
  expect(await screen.findByRole("button", { name: /Tutor report/ })).toBeInTheDocument();
  expect(screen.queryByText("No reports yet")).not.toBeInTheDocument();
});
