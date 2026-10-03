import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, test, vi } from "vitest";
import TeachingPlanInputs from "../tutor/TeachingPlanInputs";

/* Task 6.2: the plan inputs on the class. Pace is pre-filled from the
   timetable and marked as such; a missing value is blank, never 0. */

const NO_PLAN = { draft: null, accepted: null };

const DRAFT = {
  id: 1,
  exam_date: "2027-05-10",
  lessons_per_week: 2,
  lesson_minutes: 90,
  past_paper_start_date: null,
  breaks: [{ id: 9, start_date: "2027-02-01", end_date: "2027-02-07", label: "Half term" }],
};

function stub(
  defaults: { lessons_per_week: number | null; lesson_minutes: number | null },
  initial: Record<string, unknown> | null = null,
  /** Holds every PUT until released, to observe a save that is still pending. */
  putGate?: Promise<void>,
) {
  const calls: { method: string; url: string; body?: Record<string, unknown> }[] = [];
  let saved: Record<string, unknown> | null = initial;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), "http://localhost");
      const method = (init?.method ?? "GET").toUpperCase();
      const body = init?.body ? JSON.parse(String(init.body)) : undefined;
      calls.push({ method, url: url.pathname, body });
      const json = (b: unknown) => new Response(JSON.stringify(b), { status: 200 });
      if (method === "POST") {
        const created = { id: 10, ...body };
        saved = { ...saved, breaks: [...((saved?.breaks as unknown[]) ?? []), created] };
        return new Response(JSON.stringify(created), { status: 201 });
      }
      if (method === "DELETE") {
        const id = Number(url.pathname.split("/").at(-1));
        const kept = ((saved?.breaks as { id: number }[]) ?? []).filter((b) => b.id !== id);
        saved = { ...saved, breaks: kept };
        return new Response(null, { status: 204 });
      }
      if (method === "PUT") {
        await putGate;
        saved = { id: 1, breaks: [], ...body };
        return json({ ...NO_PLAN, draft: saved, timetable_defaults: defaults });
      }
      return json({ ...NO_PLAN, draft: saved, timetable_defaults: defaults });
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

test("after saving, the saved values show and the timetable marker does not return", async () => {
  stub({ lessons_per_week: 2, lesson_minutes: 90 });
  renderForm();

  fireEvent.change(await screen.findByLabelText("Exam date"), { target: { value: "2027-05-10" } });
  fireEvent.click(screen.getByRole("button", { name: "Save plan inputs" }));

  await waitFor(() => expect(screen.queryByText("From your timetable")).toBeNull());
  expect(screen.getByLabelText("Exam date")).toHaveValue("2027-05-10");
  expect(screen.getByLabelText("Lessons per week")).toHaveValue(2);
  expect(screen.queryByText("Save the plan inputs first, then add breaks.")).toBeNull();
});

const DEFAULTS = { lessons_per_week: 2, lesson_minutes: 90 };

test("adding a break posts the dates and label", async () => {
  const calls = stub(DEFAULTS, DRAFT);
  renderForm();

  fireEvent.change(await screen.findByLabelText("Break starts"), {
    target: { value: "2027-04-01" },
  });
  fireEvent.change(screen.getByLabelText("Break ends"), { target: { value: "2027-04-12" } });
  fireEvent.change(screen.getByLabelText("Label"), { target: { value: "Easter" } });
  fireEvent.click(screen.getByRole("button", { name: "Add break" }));

  await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
  const post = calls.find((c) => c.method === "POST")!;
  expect(post.url).toBe("/api/v1/groups/5/plan/breaks");
  expect(post.body).toEqual({ start_date: "2027-04-01", end_date: "2027-04-12", label: "Easter" });
  await waitFor(() => expect(screen.getByLabelText("Label")).toHaveValue(""));
  expect(await screen.findByText("Easter")).toBeInTheDocument();
  expect(screen.getByText("Half term")).toBeInTheDocument();
});

test("removing a break deletes that break", async () => {
  const calls = stub(DEFAULTS, DRAFT);
  renderForm();

  fireEvent.click(await screen.findByRole("button", { name: "Remove the Half term break" }));

  await waitFor(() => expect(calls.some((c) => c.method === "DELETE")).toBe(true));
  expect(calls.find((c) => c.method === "DELETE")!.url).toBe("/api/v1/groups/5/plan/breaks/9");
  await waitFor(() => expect(screen.queryByText("Half term")).toBeNull());
  expect(screen.getByText("No breaks added.")).toBeInTheDocument();
});

test("Enter in an incomplete form does not submit it", async () => {
  const calls = stub({ lessons_per_week: null, lesson_minutes: null });
  renderForm();

  const perWeek = await screen.findByLabelText("Lessons per week");
  fireEvent.submit(perWeek.closest("form")!);
  await new Promise((r) => setTimeout(r, 20));
  expect(calls.some((c) => c.method === "PUT")).toBe(false);
});

test("typing the timetable value back in does not restore the marker", async () => {
  stub(DEFAULTS);
  renderForm();

  const perWeek = await screen.findByLabelText("Lessons per week");
  fireEvent.change(perWeek, { target: { value: "3" } });
  fireEvent.change(perWeek, { target: { value: "2" } });
  expect(screen.getAllByText("From your timetable")).toHaveLength(1);
});

test("Enter during a pending save sends only one PUT", async () => {
  let release!: () => void;
  const gate = new Promise<void>((resolve) => (release = resolve));
  const calls = stub(DEFAULTS, DRAFT, gate);
  renderForm();

  const form = (await screen.findByLabelText("Exam date")).closest("form")!;
  fireEvent.submit(form);
  await waitFor(() => expect(calls.filter((c) => c.method === "PUT")).toHaveLength(1));
  fireEvent.submit(form);
  fireEvent.submit(form);
  release();
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Save plan inputs" })).toBeEnabled(),
  );
  expect(calls.filter((c) => c.method === "PUT")).toHaveLength(1);
});
