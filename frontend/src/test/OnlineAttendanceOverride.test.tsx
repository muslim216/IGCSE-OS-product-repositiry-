import { fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, test, vi } from "vitest";
import OnlineAttendance from "../tutor/OnlineAttendance";

/* The tutor has the final say (PROD-7): an imported mark can be overridden, is
   written with source tutor through the ordinary PUT, and then reads "set by you". */

afterEach(() => vi.unstubAllGlobals());

test("the tutor can override an imported mark, and it then reads set by you", async () => {
  let row = { student_id: 11, name: "Sara", state: "absent", source: "zoom", recorded_at: null };
  const puts: unknown[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = (init?.method ?? "GET").toUpperCase();
      if (url.endsWith("/meeting")) {
        return new Response(
          JSON.stringify({
            provider: "zoom",
            link: "https://zoom.us/j/1",
            last_import: null,
            participants: [],
          }),
          { status: 200 },
        );
      }
      if (url.endsWith("/api/v1/integrations")) return new Response("[]", { status: 200 });
      if (url.endsWith("/attendance")) {
        if (method === "PUT") {
          puts.push(JSON.parse(String(init?.body)));
          row = { ...row, state: "present", source: "tutor" };
        }
        return new Response(JSON.stringify([row]), { status: 200 });
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

  expect(await screen.findByText("from Zoom")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Present: Sara" }));
  expect(await screen.findByText("set by you")).toBeInTheDocument();
  expect(screen.queryByText("from Zoom")).not.toBeInTheDocument();
  expect(puts).toEqual([{ entries: [{ student_id: 11, state: "present" }] }]);
});
