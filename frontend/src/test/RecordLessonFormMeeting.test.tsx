import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, test, vi } from "vitest";
import RecordLessonForm from "../tutor/RecordLessonForm";

/* Task 7.3: the meeting link on the record form. The server validates it, so the
   field is plain text and the app's own message shows; an in-person lesson never
   sends one. */

function stub(postStatus = 201) {
  const posts: Record<string, unknown>[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), "http://localhost");
      const json = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status });
      const method = init?.method ?? "GET";
      if (method === "POST" && url.pathname === "/api/v1/lessons") {
        posts.push(JSON.parse(String(init?.body)));
        return postStatus === 201
          ? json({ id: 1 }, 201)
          : json({ detail: "That isn't a Zoom or Google Meet link." }, postStatus);
      }
      if (url.pathname.endsWith("/next-lesson")) return json(null);
      if (url.pathname.endsWith("/topics")) return json([]);
      if (url.pathname.endsWith("/me/organization"))
        return json({ id: 1, name: "Org", timezone: "UTC" });
      if (url.pathname.endsWith("/plan"))
        return json({
          draft: null,
          accepted: null,
          timetable_defaults: { lessons_per_week: null, lesson_minutes: null },
        });
      return json([]);
    }),
  );
  return posts;
}

function renderForm() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <RecordLessonForm groupId={5} subjectId={3} />
    </QueryClientProvider>,
  );
}

const submit = () => screen.getByRole("button", { name: "Record lesson" });
const ready = () => waitFor(() => expect(submit()).toBeEnabled());

afterEach(() => vi.unstubAllGlobals());

test("an online lesson sends the pasted link", async () => {
  const posts = stub();
  renderForm();
  await ready();
  fireEvent.change(screen.getByLabelText("Mode"), { target: { value: "online" } });
  const link = screen.getByLabelText(/Meeting link/);
  expect(link).toHaveAttribute("type", "text");
  fireEvent.change(link, { target: { value: "  https://zoom.us/j/81234567890  " } });
  fireEvent.click(submit());
  await waitFor(() => expect(posts).toHaveLength(1));
  expect(posts[0]).toMatchObject({ mode: "online", meeting_link: "https://zoom.us/j/81234567890" });
});

test("an online lesson without a link sends none", async () => {
  const posts = stub();
  renderForm();
  await ready();
  fireEvent.change(screen.getByLabelText("Mode"), { target: { value: "online" } });
  fireEvent.click(submit());
  await waitFor(() => expect(posts).toHaveLength(1));
  expect(posts[0].mode).toBe("online");
  expect("meeting_link" in posts[0]).toBe(false);
});

test("an in-person lesson never sends a link, even one typed before switching back", async () => {
  const posts = stub();
  renderForm();
  await ready();
  fireEvent.change(screen.getByLabelText("Mode"), { target: { value: "online" } });
  fireEvent.change(screen.getByLabelText(/Meeting link/), {
    target: { value: "https://zoom.us/j/81234567890" },
  });
  fireEvent.change(screen.getByLabelText("Mode"), { target: { value: "in_person" } });
  expect(screen.queryByLabelText(/Meeting link/)).not.toBeInTheDocument();
  fireEvent.click(submit());
  await waitFor(() => expect(posts).toHaveLength(1));
  expect(posts[0].mode).toBe("in_person");
  expect("meeting_link" in posts[0]).toBe(false);
});

test("the server's own message shows when the link is not a Zoom or Meet one", async () => {
  stub(422);
  renderForm();
  await ready();
  fireEvent.change(screen.getByLabelText("Mode"), { target: { value: "online" } });
  fireEvent.change(screen.getByLabelText(/Meeting link/), { target: { value: "nonsense" } });
  fireEvent.click(submit());
  expect(await screen.findByText("That isn't a Zoom or Google Meet link.")).toBeInTheDocument();
});
