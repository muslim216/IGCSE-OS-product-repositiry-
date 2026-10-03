import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, test, vi } from "vitest";
import TeachingPlanInputs from "../tutor/TeachingPlanInputs";

/* Task 6.2: the plan inputs on the class. Pace is pre-filled from the
   timetable and marked as such; a missing value is blank, never 0. */

const NO_PLAN = { draft: null, accepted: null };

function stub(defaults: { lessons_per_week: number | null; lesson_minutes: number | null }) {
  const calls: { method: string; url: string; body?: Record<string, unknown> }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), "http://localhost");
      const method = (init?.method ?? "GET").toUpperCase();
      const body = init?.body ? JSON.parse(String(init.body)) : undefined;
      calls.push({ method, url: url.pathname, body });
      const json = (b: unknown) => new Response(JSON.stringify(b), { status: 200 });
      if (method === "PUT")
        return json({
          ...NO_PLAN,
          draft: { id: 1, breaks: [], ...body },
          timetable_defaults: defaults,
        });
      return json({ ...NO_PLAN, timetable_defaults: defaults });
    }),
  );
  return calls;
}

function renderForm() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <TeachingPlanInputs groupId={5} />
    </QueryClientProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

test("pace is pre-filled from the timetable, marked, and saves through the API", async () => {
  const calls = stub({ lessons_per_week: 2, lesson_minutes: 90 });
  renderForm();

  const perWeek = await screen.findByLabelText("Lessons per week");
  expect(perWeek).toHaveValue(2);
  expect(screen.getByLabelText("Lesson length (minutes)")).toHaveValue(90);
  expect(screen.getAllByText("From your timetable")).toHaveLength(2);

  // Changing a pre-filled value makes it the tutor's own.
  fireEvent.change(perWeek, { target: { value: "3" } });
  expect(screen.getAllByText("From your timetable")).toHaveLength(1);

  fireEvent.change(screen.getByLabelText("Exam date"), { target: { value: "2027-05-10" } });
  fireEvent.click(screen.getByRole("button", { name: "Save plan inputs" }));

  await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
  const put = calls.find((c) => c.method === "PUT")!;
  expect(put.url).toBe("/api/v1/groups/5/plan/inputs");
  expect(put.body).toEqual({
    exam_date: "2027-05-10",
    lessons_per_week: 3,
    lesson_minutes: 90,
    past_paper_start_date: null,
  });
});

test("without a timetable nothing is pre-filled and save stays disabled", async () => {
  stub({ lessons_per_week: null, lesson_minutes: null });
  renderForm();

  expect(await screen.findByLabelText("Lessons per week")).toHaveValue(null);
  expect(screen.getByLabelText("Lesson length (minutes)")).toHaveValue(null);
  expect(screen.queryByText("From your timetable")).toBeNull();
  expect(screen.getByRole("button", { name: "Save plan inputs" })).toBeDisabled();
  expect(screen.getByText("Save the plan inputs first, then add breaks.")).toBeInTheDocument();
});
