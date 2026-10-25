import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, test, vi } from "vitest";
import DeleteChildData from "../components/DeleteChildData";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function renderIt(asker: "tutor" | "parent") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <DeleteChildData asker={asker} studentId={7} name="Sara Ali" />
    </QueryClientProvider>,
  );
}

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
const req = {
  id: 1,
  status: "pending",
  scheduled_for: "2026-11-10T12:00:00Z",
  requested_role: "tutor",
  created_at: "2026-10-27T12:00:00Z",
};

type Call = { method: string; path: string; body: string | undefined };
function stub(handler: (c: Call) => Response) {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const c = {
        method: init?.method ?? "GET",
        path: new URL(url, "http://localhost").pathname,
        body: init?.body as string | undefined,
      };
      calls.push(c);
      return handler(c);
    }),
  );
  return calls;
}

const open = async (name: string) => fireEvent.click(await screen.findByRole("button", { name }));
const field = () => screen.getByLabelText("Type Sara Ali to confirm");
const del = () => screen.getByRole("button", { name: "Delete" }) as HTMLButtonElement;

test("delete stays disabled until the name matches, then posts it", async () => {
  let pending = false;
  const calls = stub(({ method }) => {
    if (method === "POST") {
      pending = true;
      return json(req, 202);
    }
    return json(pending ? req : null);
  });
  renderIt("tutor");
  await open("Delete this student's data");
  expect(screen.getByText(/deleted in 14 days/)).toBeTruthy();
  expect(del().disabled).toBe(true);
  fireEvent.change(field(), { target: { value: "sara" } });
  expect(del().disabled).toBe(true);
  fireEvent.change(field(), { target: { value: "  SARA   ali " } });
  expect(del().disabled).toBe(false);
  fireEvent.click(del());
  await screen.findByText(/will be deleted on/);
  const post = calls.find((c) => c.method === "POST")!;
  expect(post.path).toBe("/api/v1/students/7/erasure");
  expect(JSON.parse(post.body!)).toEqual({ confirm_name: "  SARA   ali " });
});

test("a pending request shows its date and Undo cancels then refetches", async () => {
  let cancelled = false;
  const calls = stub(({ method }) => {
    if (method === "DELETE") {
      cancelled = true;
      return new Response(null, { status: 204 });
    }
    return json(cancelled ? null : req);
  });
  renderIt("tutor");
  const note = await screen.findByRole("status");
  expect(note.textContent).toMatch(
    /Sara Ali's data will be deleted on (10 Nov|Nov 10)\. They can't sign in until then\./,
  );
  await open("Undo");
  await screen.findByRole("button", { name: "Delete this student's data" });
  expect(calls.map((c) => c.method)).toEqual(["GET", "DELETE", "GET"]);
});

test("a name the server refuses says so", async () => {
  stub(({ method }) =>
    method === "POST" ? json({ detail: "Name does not match" }, 422) : json(null),
  );
  renderIt("tutor");
  await open("Delete this student's data");
  fireEvent.change(field(), { target: { value: "Sara Ali" } });
  fireEvent.click(del());
  const alert = await screen.findByRole("alert");
  expect(alert.textContent).toBe("That name doesn't match.");
});

test("any other failure is said plainly", async () => {
  stub(({ method }) => (method === "POST" ? json({ detail: "boom" }, 500) : json(null)));
  renderIt("tutor");
  await open("Delete this student's data");
  fireEvent.change(field(), { target: { value: "Sara Ali" } });
  fireEvent.click(del());
  const alert = await screen.findByRole("alert");
  expect(alert.textContent).toBe("Couldn't do that right now. Try again.");
});

test("a parent uses their own child's routes and wording; Cancel closes the panel", async () => {
  const calls = stub(() => json(null));
  renderIt("parent");
  await open("Delete my child's data");
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  await screen.findByRole("button", { name: "Delete my child's data" });
  expect(calls).toHaveLength(1);
  expect(calls[0].path).toBe("/api/v1/me/children/7/erasure");
  await waitFor(() => expect(screen.queryByLabelText(/Type Sara Ali/)).toBeNull());
});
