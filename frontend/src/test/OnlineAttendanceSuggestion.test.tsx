import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, test, vi } from "vitest";
import OnlineAttendance from "../tutor/OnlineAttendance";

/* A Zoom guest types their own email, so a match on it is only a suggestion: the
   tutor confirms it with one tap, and until then nothing is marked. */

afterEach(() => vi.unstubAllGlobals());

test("an unverified email match is offered for one-tap confirmation", async () => {
  const resolves: unknown[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/meeting")) {
        return new Response(
          JSON.stringify({
            provider: "zoom",
            link: "https://zoom.us/j/1",
            last_import: null,
            participants: [
              {
                id: 5,
                display_name: "totally not sara",
                email: "sara@example.com",
                duration_seconds: 900,
                matched_student_id: null,
                suggested_student_id: 11,
                resolved: false,
              },
            ],
          }),
          { status: 200 },
        );
      }
      if (url.endsWith("/api/v1/integrations")) return new Response("[]", { status: 200 });
      if (url.includes("/resolve")) {
        resolves.push(JSON.parse(String(init?.body)));
        return new Response("{}", { status: 200 });
      }
      if (url.endsWith("/attendance")) {
        return new Response(
          JSON.stringify([
            { student_id: 11, name: "Sara", state: null, source: null, recorded_at: null },
          ]),
          { status: 200 },
        );
      }
      return new Response("{}", { status: 200 });
    }),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <OnlineAttendance lessonId={9} />
      </MemoryRouter>
    </QueryClientProvider>,
  );

  expect(await screen.findByText(/doesn't verify it, so it needs your say-so/)).toBeInTheDocument();
  expect(screen.getByText("Not taken")).toBeInTheDocument();
  fireEvent.click(await screen.findByRole("button", { name: "Confirm: Sara" }));
  await waitFor(() => expect(resolves).toEqual([{ student_id: 11 }]));
});
