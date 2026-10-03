import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, test, vi } from "vitest";
import { dayKeyIn } from "../lib/timezones";
import RecordLessonForm from "../tutor/RecordLessonForm";

/* Task 6.5 (AV-17): the plan pre-fills the form; the tutor decides. */

const TOPICS = [
  { id: 11, code: "1.1", title: "Atoms", parent_id: null, weight: 1 },
  { id: 12, code: "1.2", title: "Isotopes", parent_id: null, weight: 1 },
  { id: 13, code: "2.1", title: "Bonding", parent_id: null, weight: 1 },
];

const SUGGESTION = {
  slot_id: 7,
  scheduled_date: "2026-10-13",
  chapter: { id: 1, code: "4", title: "Organic chemistry" },
  topics: [
    { id: 11, code: "1.1", title: "Atoms" },
    { id: 12, code: "1.2", title: "Isotopes" },
  ],
};

const SECOND = {
  slot_id: 8,
  scheduled_date: "2026-10-20",
  chapter: { id: 2, code: "5", title: "Metals" },
  topics: [{ id: 13, code: "2.1", title: "Bonding" }],
};

interface Setup {
  suggestion?: unknown;
  acceptedMinutes?: number | null;
  timetable?: { weekday: number; duration_min: number }[];
  defaultMinutes?: number | null;
  postStatus?: number;
  orgZone?: string | null;
}

function stub(setup: Setup = {}) {
  const state = { suggestion: setup.suggestion ?? (null as unknown) };
  const posts: Record<string, unknown>[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), "http://localhost");
      const json = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status });
      if (url.pathname.endsWith("/next-lesson")) return json(state.suggestion);
      if (url.pathname.endsWith("/topics")) return json(TOPICS);
      if (url.pathname.endsWith("/me/organization"))
        return json({ id: 1, name: "Org", timezone: setup.orgZone ?? null });
      if (url.pathname.endsWith("/plan"))
        return json({
          draft: null,
          accepted:
            setup.acceptedMinutes != null
              ? { id: 1, lesson_minutes: setup.acceptedMinutes, breaks: [], slots: [] }
              : null,
          timetable_defaults: {
            lessons_per_week: null,
            lesson_minutes: setup.defaultMinutes ?? null,
          },
        });
      if (url.pathname.endsWith("/lessons") && (init?.method ?? "GET") === "GET")
        return json(setup.timetable ?? []);
      if ((init?.method ?? "GET") === "POST" && url.pathname === "/api/v1/lessons") {
        posts.push(JSON.parse(String(init?.body)));
        if (setup.postStatus && setup.postStatus !== 201)
          return json({ detail: "A lesson already covers that planned lesson" }, setup.postStatus);
        return json({ id: 1 }, 201);
      }
      return json({});
    }),
  );
  return { posts, state };
}

function renderForm() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const invalidate = vi.spyOn(client, "invalidateQueries");
  render(
    <QueryClientProvider client={client}>
      <RecordLessonForm groupId={5} subjectId={3} />
    </QueryClientProvider>,
  );
  return { client, invalidate };
}

const submit = () => screen.getByRole("button", { name: "Record lesson" });
const ready = async () => {
  await screen.findByRole("checkbox", { name: /Atoms/ });
  await waitFor(() => expect(submit()).toBeEnabled());
};

afterEach(() => vi.unstubAllGlobals());

test("the suggestion pre-fills the date and topics and says where it came from", async () => {
  stub({ suggestion: SUGGESTION });
  renderForm();
  expect(
    await screen.findByText(/Suggested by your plan: Chapter 4 · Organic chemistry/),
  ).toHaveTextContent("planned Tue 13 Oct");
  await waitFor(() => expect(screen.getByLabelText("Date")).toHaveValue("2026-10-13"));
  expect(screen.getByRole("checkbox", { name: /Atoms/ })).toBeChecked();
  expect(screen.getByRole("checkbox", { name: /Isotopes/ })).toBeChecked();
  expect(screen.getByRole("checkbox", { name: /Bonding/ })).not.toBeChecked();
});

test("a kept suggestion sends the slot and the topics exactly as the tutor left them", async () => {
  const { posts } = stub({ suggestion: SUGGESTION });
  renderForm();
  await waitFor(() => expect(screen.getByRole("checkbox", { name: /Atoms/ })).toBeChecked());
  fireEvent.click(screen.getByRole("checkbox", { name: /Isotopes/ })); // untick one
  fireEvent.click(screen.getByRole("checkbox", { name: /Bonding/ })); // tick another
  await waitFor(() => expect(submit()).toBeEnabled());
  fireEvent.click(submit());
  await waitFor(() => expect(posts).toHaveLength(1));
  expect(posts[0]).toMatchObject({ group_id: 5, date: "2026-10-13", plan_slot_id: 7 });
  expect([...(posts[0].topic_ids as number[])].sort()).toEqual([11, 13]);
});

test("dropping the suggestion sends no slot and clears the pre-fill", async () => {
  const { posts } = stub({ suggestion: SUGGESTION });
  renderForm();
  fireEvent.click(await screen.findByRole("button", { name: "Don't use the plan suggestion" }));
  expect(screen.queryByText(/Suggested by your plan/)).not.toBeInTheDocument();
  expect(screen.getByRole("checkbox", { name: /Atoms/ })).not.toBeChecked();
  fireEvent.click(screen.getByRole("checkbox", { name: /Bonding/ }));
  await waitFor(() => expect(submit()).toBeEnabled());
  fireEvent.click(submit());
  await waitFor(() => expect(posts).toHaveLength(1));
  expect(posts[0]).not.toHaveProperty("plan_slot_id");
  expect(posts[0].topic_ids).toEqual([13]);
});

test("with no suggestion there is no plan line and no slot is sent", async () => {
  const { posts } = stub();
  renderForm();
  await ready();
  expect(screen.queryByText(/Suggested by your plan/)).not.toBeInTheDocument();
  fireEvent.click(submit());
  await waitFor(() => expect(posts).toHaveLength(1));
  expect(posts[0]).not.toHaveProperty("plan_slot_id");
});

test("the duration is seeded from the accepted plan and the tutor can change it", async () => {
  const { posts } = stub({ acceptedMinutes: 45, timetable: [{ weekday: 1, duration_min: 90 }] });
  renderForm();
  await waitFor(() => expect(screen.getByLabelText("Duration (min)")).toHaveValue(45));
  fireEvent.change(screen.getByLabelText("Duration (min)"), { target: { value: "50" } });
  fireEvent.click(submit());
  await waitFor(() => expect(posts).toHaveLength(1));
  expect(posts[0].duration_min).toBe(50);
});

// 2026-10-13 is a Tuesday: weekday 1, Monday first.
test("without a plan the duration comes from the timetable slot on that weekday", async () => {
  stub({
    suggestion: SUGGESTION,
    timetable: [
      { weekday: 0, duration_min: 30 },
      { weekday: 1, duration_min: 90 },
    ],
    defaultMinutes: 75,
  });
  renderForm();
  await waitFor(() => expect(screen.getByLabelText("Duration (min)")).toHaveValue(90));
});

test("without a plan or a matching weekday the duration is the timetable default", async () => {
  stub({ defaultMinutes: 75 });
  renderForm();
  await waitFor(() => expect(screen.getByLabelText("Duration (min)")).toHaveValue(75));
});

test("with nothing known the duration is 60", async () => {
  stub();
  renderForm();
  await waitFor(() => expect(screen.getByLabelText("Duration (min)")).toHaveValue(60));
});

test("the default date is today in the tutor's effective zone, not the browser's", async () => {
  // 10:30 UTC on 2 October is already 00:30 on 3 October in Kiritimati (UTC+14),
  // so the zone and the UTC/browser date always differ and this cannot pass by
  // coincidence of when the suite runs.
  vi.useFakeTimers({ toFake: ["Date"], now: new Date("2026-10-02T10:30:00Z") });
  try {
    stub({ orgZone: "Pacific/Kiritimati" });
    renderForm();
    await waitFor(() => expect(screen.getByLabelText("Date")).toHaveValue("2026-10-03"));
    expect(dayKeyIn(new Date(), "UTC")).toBe("2026-10-02");
  } finally {
    vi.useRealTimers();
  }
});

test("after a save the form resets, the old slot is not reused and the next suggestion loads", async () => {
  const { posts, state } = stub({ suggestion: SUGGESTION });
  const { invalidate } = renderForm();
  await waitFor(() => expect(screen.getByRole("checkbox", { name: /Atoms/ })).toBeChecked());
  await waitFor(() => expect(submit()).toBeEnabled());
  state.suggestion = SECOND; // what the server will say once the slot is confirmed
  fireEvent.click(submit());
  expect(await screen.findByRole("status")).toHaveTextContent("Lesson recorded.");
  // The next suggestion seeds the reset form.
  await waitFor(() => expect(screen.getByLabelText("Date")).toHaveValue("2026-10-20"));
  expect(screen.getByRole("checkbox", { name: /Bonding/ })).toBeChecked();
  expect(screen.getByRole("checkbox", { name: /Atoms/ })).not.toBeChecked();
  expect(screen.getByText(/Chapter 5 · Metals/)).toBeInTheDocument();
  const keys = invalidate.mock.calls.map((c) => JSON.stringify(c[0]?.queryKey));
  for (const key of [
    '["analytics",5]',
    '["class-overview",5]',
    '["today"]',
    '["group",5]',
    '["next-lesson",5]',
    '["plan",5]',
  ]) {
    expect(keys).toContain(key);
  }
  await waitFor(() => expect(submit()).toBeEnabled());
  fireEvent.click(submit());
  await waitFor(() => expect(posts).toHaveLength(2));
  expect(posts[1]).toMatchObject({ plan_slot_id: 8 });
});

test("the saved status clears on the next edit", async () => {
  stub();
  renderForm();
  await ready();
  fireEvent.click(submit());
  await screen.findByRole("status");
  fireEvent.click(screen.getByRole("checkbox", { name: /Atoms/ }));
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
});

test("a touched form is not overwritten by a new suggestion, which is offered instead", async () => {
  const { state } = stub({ suggestion: SUGGESTION });
  const { client } = renderForm();
  await waitFor(() => expect(screen.getByRole("checkbox", { name: /Atoms/ })).toBeChecked());
  fireEvent.click(screen.getByRole("checkbox", { name: /Bonding/ })); // the tutor edits
  state.suggestion = SECOND;
  await act(() => client.invalidateQueries({ queryKey: ["next-lesson", 5] }));
  expect(await screen.findByText(/Your plan now suggests Chapter 5 · Metals/)).toBeInTheDocument();
  expect(screen.getByLabelText("Date")).toHaveValue("2026-10-13");
  expect(screen.getByRole("checkbox", { name: /Atoms/ })).toBeChecked();
  expect(screen.getByRole("checkbox", { name: /Bonding/ })).toBeChecked();
  fireEvent.click(screen.getByRole("button", { name: "Apply" }));
  await waitFor(() => expect(screen.getByLabelText("Date")).toHaveValue("2026-10-20"));
  expect(screen.getByRole("checkbox", { name: /Atoms/ })).not.toBeChecked();
});

test("a 409 shows the server's message", async () => {
  stub({ suggestion: SUGGESTION, postStatus: 409 });
  renderForm();
  await waitFor(() => expect(screen.getByRole("checkbox", { name: /Atoms/ })).toBeChecked());
  await waitFor(() => expect(submit()).toBeEnabled());
  fireEvent.click(submit());
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "A lesson already covers that planned lesson",
  );
});
