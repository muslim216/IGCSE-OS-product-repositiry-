import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, test, vi } from "vitest";
import { ReportsPanel } from "../components/ReportsPanel";

/* `POST /reports/generate` answers 409 with a plain sentence when there is
   nothing to report. The panel used to swallow it: the button re-enabled and
   the tutor was told nothing. */

const NOTHING = "This student isn't in a class yet, so there is nothing to report.";

const REPORT = {
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

/** Each POST consumes the next queued outcome; GETs return an empty list or the report. */
function stub(posts: ("conflict" | "ok")[]) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = new URL(String(input), "http://localhost").pathname;
      if ((init?.method ?? "GET").toUpperCase() === "POST") {
        return posts.shift() === "conflict"
          ? new Response(JSON.stringify({ detail: NOTHING }), { status: 409 })
          : new Response(JSON.stringify(REPORT), { status: 200 });
      }
      return new Response(JSON.stringify(path.endsWith("/reports") ? [] : REPORT), {
        status: 200,
      });
    }),
  );
}

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ReportsPanel studentId={2} audiences={["tutor"]} />
    </QueryClientProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

test("a 409 from generate shows the server's sentence in an alert", async () => {
  stub(["conflict"]);
  renderPanel();

  fireEvent.click(screen.getByRole("button", { name: "Generate report" }));

  expect(await screen.findByRole("alert")).toHaveTextContent(NOTHING);
  expect(screen.getByRole("button", { name: "Generate report" })).toBeEnabled();
});

test("a later successful generate clears the alert", async () => {
  stub(["conflict", "ok"]);
  renderPanel();

  fireEvent.click(screen.getByRole("button", { name: "Generate report" }));
  await screen.findByRole("alert");

  fireEvent.click(screen.getByRole("button", { name: "Generate report" }));

  expect(await screen.findByText("Writing the report…")).toBeInTheDocument();
  await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
});
