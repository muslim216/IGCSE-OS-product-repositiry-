import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, test, vi } from "vitest";
import RecordedLessons from "../tutor/RecordedLessons";

/* Each register is its own request, so only the latest lessons load one on open. */

const lessons = [1, 2, 3, 4, 5].map((id) => ({
  id,
  group_id: 7,
  date: `2026-10-0${id}`,
  duration_min: 60,
  notes: null,
  schedule_slot_id: null,
  mode: "in_person",
  start_time: null,
  origin: "tutor",
  topics: [],
}));

afterEach(() => vi.unstubAllGlobals());

test("only the latest three lessons fetch a register until older ones are asked for", async () => {
  const urls: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      urls.push(url);
      const body = url.includes("/attendance") ? [] : lessons;
      return new Response(JSON.stringify(body), { status: 200 });
    }),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <RecordedLessons groupId={7} />
    </QueryClientProvider>,
  );
  const more = await screen.findByRole("button", { name: "Show 2 older lessons" });
  await screen.findAllByText("No students in this class yet.");
  expect(urls.filter((u) => u.includes("/attendance"))).toHaveLength(3);

  fireEvent.click(more);
  await waitFor(() =>
    expect(screen.getAllByText("No students in this class yet.")).toHaveLength(5),
  );
  expect(urls.filter((u) => u.includes("/attendance"))).toHaveLength(5);
});
