import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, test, vi } from "vitest";
import RecordLessonForm from "../tutor/RecordLessonForm";

/* Task 7.4 (AV-120): Review on a reminder opens the form for that planned lesson. */

const SLOT_9 = {
  slot_id: 9,
  scheduled_date: "2026-10-15",
  chapter: { id: 2, code: "5", title: "Metals" },
  topics: [{ id: 13, code: "2.1", title: "Bonding" }],
};
const EARLIEST = { ...SLOT_9, slot_id: 7, topics: [{ id: 11, code: "1.1", title: "Atoms" }] };

function stub(reviewable: boolean) {
  const urls: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), "http://localhost");
      urls.push(url.pathname + url.search);
      const json = (b: unknown) => new Response(JSON.stringify(b), { status: 200 });
      if (url.pathname.endsWith("/next-lesson")) {
        if (url.searchParams.get("slot_id") === "9") return json(reviewable ? SLOT_9 : null);
        return json(EARLIEST);
      }
      if (url.pathname.endsWith("/topics"))
        return json([
          { id: 11, code: "1.1", title: "Atoms", parent_id: null, weight: 1 },
          { id: 13, code: "2.1", title: "Bonding", parent_id: null, weight: 1 },
        ]);
      if (url.pathname.endsWith("/me/organization"))
        return json({ id: 1, name: "Org", timezone: null });
      if (url.pathname.endsWith("/plan"))
        return json({
          draft: null,
          accepted: null,
          timetable_defaults: { lessons_per_week: null, lesson_minutes: null },
        });
      return json([]);
    }),
  );
  return urls;
}

function renderForm() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <RecordLessonForm groupId={5} subjectId={3} />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.pushState({}, "", "/");
});

test("?slot= pre-fills from that planned lesson, not the earliest unstarted one", async () => {
  window.history.pushState({}, "", "/tutor/groups/5/schedule?slot=9");
  const urls = stub(true);
  renderForm();
  await waitFor(() => expect(screen.getByRole("checkbox", { name: /Bonding/ })).toBeChecked());
  expect(screen.getByRole("checkbox", { name: /Atoms/ })).not.toBeChecked();
  expect(urls.some((u) => u.includes("slot_id=9"))).toBe(true);
});

test("a slot that is no longer open says so and does not borrow another lesson's topics", async () => {
  window.history.pushState({}, "", "/tutor/groups/5/schedule?slot=9");
  stub(false);
  renderForm();
  expect(
    await screen.findByText(/no longer open — it was recorded or cancelled/),
  ).toBeInTheDocument();
  expect(screen.getByRole("checkbox", { name: /Atoms/ })).not.toBeChecked();
  expect(screen.getByRole("checkbox", { name: /Bonding/ })).not.toBeChecked();
  // The tutor may choose the plan's next lesson instead.
  fireEvent.click(screen.getByRole("button", { name: "Use the next planned lesson" }));
  await waitFor(() => expect(screen.getByRole("checkbox", { name: /Atoms/ })).toBeChecked());
});

test("a junk slot parameter is ignored", async () => {
  window.history.pushState({}, "", "/tutor/groups/5/schedule?slot=abc");
  const urls = stub(true);
  renderForm();
  await waitFor(() => expect(screen.getByRole("checkbox", { name: /Atoms/ })).toBeChecked());
  expect(urls.some((u) => u.includes("slot_id"))).toBe(false);
});

test("after a successful save the ?slot= override is cleared so the next lesson prefills", async () => {
  window.history.pushState({}, "", "/tutor/groups/5/schedule?slot=9");
  const urls = stub(true);
  const fetchMock = globalThis.fetch as unknown as ReturnType<typeof vi.fn>;
  const inner = fetchMock.getMockImplementation()!;
  fetchMock.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), "http://localhost");
    if (init?.method === "POST" && url.pathname.endsWith("/lessons"))
      return new Response(JSON.stringify({ id: 1 }), { status: 201 });
    return inner(input, init);
  });
  renderForm();
  await waitFor(() => expect(screen.getByRole("checkbox", { name: /Bonding/ })).toBeChecked());
  fireEvent.click(screen.getByRole("button", { name: "Record lesson" }));
  await waitFor(() => expect(window.location.search).toBe(""));
  await waitFor(() =>
    expect(
      urls.filter((u) => u.includes("/next-lesson") && !u.includes("slot_id")).length,
    ).toBeGreaterThan(0),
  );
});

test("?date= dates the lesson that day, not the slot's own date (Record on today's agenda)", async () => {
  window.history.pushState({}, "", "/tutor/groups/5/schedule?slot=9&date=2026-10-07");
  stub(true);
  renderForm();
  await waitFor(() => expect(screen.getByRole("checkbox", { name: /Bonding/ })).toBeChecked());
  expect(screen.getByLabelText("Date")).toHaveValue("2026-10-07");
});

test("a malformed ?date= is ignored and the slot's date is used", async () => {
  window.history.pushState({}, "", "/tutor/groups/5/schedule?slot=9&date=tomorrow");
  stub(true);
  renderForm();
  await waitFor(() => expect(screen.getByRole("checkbox", { name: /Bonding/ })).toBeChecked());
  expect(screen.getByLabelText("Date")).toHaveValue("2026-10-15");
});
