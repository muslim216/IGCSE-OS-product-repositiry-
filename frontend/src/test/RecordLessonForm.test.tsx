import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, test, vi } from "vitest";
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

function stub(suggestion: unknown) {
  const posts: Record<string, unknown>[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), "http://localhost");
      const json = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status });
      if (url.pathname.endsWith("/next-lesson")) return json(suggestion);
      if (url.pathname.endsWith("/topics")) return json(TOPICS);
      if ((init?.method ?? "GET") === "POST" && url.pathname === "/api/v1/lessons") {
        posts.push(JSON.parse(String(init?.body)));
        return json({ id: 1 }, 201);
      }
      return json({});
    }),
  );
  return posts;
}

function renderForm() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <RecordLessonForm groupId={5} subjectId={3} />
    </QueryClientProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

test("the suggestion pre-fills the date and topics and says where it came from", async () => {
  stub(SUGGESTION);
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
  const posts = stub(SUGGESTION);
  renderForm();
  await screen.findByText(/Suggested by your plan/);
  await waitFor(() => expect(screen.getByRole("checkbox", { name: /Atoms/ })).toBeChecked());
  fireEvent.click(screen.getByRole("checkbox", { name: /Isotopes/ })); // untick one
  fireEvent.click(screen.getByRole("checkbox", { name: /Bonding/ })); // tick another
  fireEvent.click(screen.getByRole("button", { name: "Record lesson" }));
  await waitFor(() => expect(posts).toHaveLength(1));
  expect(posts[0]).toMatchObject({ group_id: 5, date: "2026-10-13", plan_slot_id: 7 });
  expect([...(posts[0].topic_ids as number[])].sort()).toEqual([11, 13]);
});

test("dropping the suggestion sends no slot and clears the pre-fill", async () => {
  const posts = stub(SUGGESTION);
  renderForm();
  fireEvent.click(await screen.findByRole("button", { name: "Don't use the plan suggestion" }));
  expect(screen.queryByText(/Suggested by your plan/)).not.toBeInTheDocument();
  expect(screen.getByRole("checkbox", { name: /Atoms/ })).not.toBeChecked();
  fireEvent.click(screen.getByRole("checkbox", { name: /Bonding/ }));
  fireEvent.click(screen.getByRole("button", { name: "Record lesson" }));
  await waitFor(() => expect(posts).toHaveLength(1));
  expect(posts[0]).not.toHaveProperty("plan_slot_id");
  expect(posts[0].topic_ids).toEqual([13]);
});

test("with no suggestion there is no plan line and no slot is sent", async () => {
  const posts = stub(null);
  renderForm();
  await screen.findByRole("checkbox", { name: /Atoms/ });
  expect(screen.queryByText(/Suggested by your plan/)).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Record lesson" }));
  await waitFor(() => expect(posts).toHaveLength(1));
  expect(posts[0]).not.toHaveProperty("plan_slot_id");
});
