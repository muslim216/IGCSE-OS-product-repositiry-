import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, test, vi } from "vitest";
import RecordedLessons from "../tutor/RecordedLessons";

/* A lesson recorded from the plan is always in person with no link. The tutor can
   switch it to online and add the link, which is what makes Zoom/Meet import
   reachable. The server validates the link; its message is shown as written. */

const base = {
  id: 9,
  group_id: 7,
  date: "2026-10-03",
  duration_min: 60,
  notes: null,
  schedule_slot_id: null,
  mode: "in_person",
  start_time: "17:00:00",
  origin: "plan",
  meeting_provider: null,
  meeting_link: null,
  topics: [],
};

afterEach(() => vi.unstubAllGlobals());

function stub(
  patchResponse: (body: Record<string, unknown>) => Response,
  initial: Record<string, unknown> = {},
) {
  let lesson: Record<string, unknown> = { ...base, ...initial };
  const calls: { method: string; url: string; body: Record<string, unknown> | null }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = (init?.method ?? "GET").toUpperCase();
      const body = init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : null;
      calls.push({ method, url, body });
      if (method === "PATCH") {
        const resp = patchResponse(body ?? {});
        if (resp.ok) lesson = { ...lesson, ...body, meeting_provider: "zoom" };
        return resp;
      }
      if (url.endsWith("/meeting")) {
        return new Response(
          JSON.stringify({
            provider: "zoom",
            link: lesson.meeting_link,
            last_import: null,
            participants: [],
          }),
          { status: 200 },
        );
      }
      if (url.endsWith("/api/v1/integrations")) return new Response("[]", { status: 200 });
      if (url.includes("/attendance")) return new Response("[]", { status: 200 });
      return new Response(JSON.stringify([lesson]), { status: 200 });
    }),
  );
  return calls;
}

function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <RecordedLessons groupId={7} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

test("a plan-recorded lesson is labelled, and switching it online with a link reveals the online attendance", async () => {
  const calls = stub(() => new Response(JSON.stringify({ ...base }), { status: 200 }));
  mount();
  expect(await screen.findByText("Recorded from the plan")).toBeInTheDocument();
  expect(screen.queryByText(/Zoom link:/)).not.toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "Edit" }));
  fireEvent.change(screen.getByLabelText("Mode"), { target: { value: "online" } });
  fireEvent.change(screen.getByLabelText(/Meeting link/), {
    target: { value: " https://zoom.us/j/81234567890 " },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save" }));

  // The online section (the meeting link row, then the import) is now on the lesson.
  expect(await screen.findByText(/Zoom link:/)).toBeInTheDocument();
  const patch = calls.find((c) => c.method === "PATCH");
  expect(patch?.url).toContain("/api/v1/lessons/9");
  expect(patch?.body).toEqual({ mode: "online", meeting_link: "https://zoom.us/j/81234567890" });
});

test("a link the server refuses shows its message and leaves the lesson as it was", async () => {
  stub(
    () =>
      new Response(JSON.stringify({ detail: "That isn't a Zoom or Google Meet link." }), {
        status: 422,
      }),
  );
  mount();
  fireEvent.click(await screen.findByRole("button", { name: "Edit" }));
  fireEvent.change(screen.getByLabelText("Mode"), { target: { value: "online" } });
  fireEvent.change(screen.getByLabelText(/Meeting link/), { target: { value: "nope" } });
  fireEvent.click(screen.getByRole("button", { name: "Save" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("That isn't a Zoom or Google Meet");
  await waitFor(() => expect(screen.getAllByText("In person").length).toBeGreaterThan(0));
  expect(screen.queryByText(/Zoom link:/)).not.toBeInTheDocument();
});

const online = {
  mode: "online",
  meeting_provider: "zoom",
  meeting_link: "https://zoom.us/j/81234567890",
};

test("switching a lesson that has a meeting to in person asks first; Cancel aborts", async () => {
  const calls = stub(() => new Response(JSON.stringify({ ...base }), { status: 200 }), online);
  mount();
  fireEvent.click(await screen.findByRole("button", { name: "Edit" }));
  fireEvent.change(screen.getByLabelText("Mode"), { target: { value: "in_person" } });
  fireEvent.click(screen.getByRole("button", { name: "Save" }));

  expect(await screen.findByText(/removes the attendance imported from Zoom\/Meet/)).toBeVisible();
  expect(calls.some((c) => c.method === "PATCH")).toBe(false);

  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  expect(screen.queryByText(/removes the attendance imported/)).not.toBeInTheDocument();
  expect(calls.some((c) => c.method === "PATCH")).toBe(false);
});

test("Confirm saves a changed link on a lesson that has a meeting", async () => {
  const calls = stub(() => new Response(JSON.stringify({ ...base }), { status: 200 }), online);
  mount();
  fireEvent.click(await screen.findByRole("button", { name: "Edit" }));
  fireEvent.change(screen.getByLabelText(/Meeting link/), {
    target: { value: "https://zoom.us/j/99999999999" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  expect(calls.some((c) => c.method === "PATCH")).toBe(false);

  fireEvent.click(await screen.findByRole("button", { name: "Confirm" }));
  await waitFor(() => expect(calls.some((c) => c.method === "PATCH")).toBe(true));
  expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({
    mode: "online",
    meeting_link: "https://zoom.us/j/99999999999",
  });
});

test("an unchanged link on a lesson that has a meeting saves without asking", async () => {
  const calls = stub(() => new Response(JSON.stringify({ ...base }), { status: 200 }), online);
  mount();
  fireEvent.click(await screen.findByRole("button", { name: "Edit" }));
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => expect(calls.some((c) => c.method === "PATCH")).toBe(true));
});

test("saving an in-person lesson sends the mode and no link", async () => {
  const calls = stub(() => new Response(JSON.stringify({ ...base }), { status: 200 }));
  mount();
  fireEvent.click(await screen.findByRole("button", { name: "Edit" }));
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => expect(calls.some((c) => c.method === "PATCH")).toBe(true));
  expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({ mode: "in_person" });
});
