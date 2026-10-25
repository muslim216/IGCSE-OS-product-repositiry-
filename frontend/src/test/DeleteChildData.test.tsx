import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, test, vi } from "vitest";
import DeleteChildData from "../components/DeleteChildData";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function renderIt(asker: "tutor" | "parent", name = "Sara Ali") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <DeleteChildData asker={asker} studentId={7} name={name} />
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
function stub(handler: (c: Call) => Response | Promise<Response>) {
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
const del = () => screen.getByRole("button", { name: "Delete" });
const awaiting = (b: HTMLElement) => b.getAttribute("aria-disabled") === "true";
const posts = (calls: Call[]) => calls.filter((c) => c.method === "POST");

test("delete stays unavailable until the name matches, then posts it", async () => {
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
  expect(awaiting(del())).toBe(true);
  fireEvent.change(field(), { target: { value: "sara" } });
  expect(awaiting(del())).toBe(true);
  fireEvent.change(field(), { target: { value: "  SARA   ali " } });
  expect(awaiting(del())).toBe(false);
  fireEvent.click(del());
  await screen.findByText(/will be deleted on/);
  const [post] = posts(calls);
  expect(post.path).toBe("/api/v1/students/7/erasure");
  expect(JSON.parse(post.body!)).toEqual({ confirm_name: "  SARA   ali " });
});

test("a name typed in a different Unicode form still matches", async () => {
  stub(() => json(null));
  renderIt("tutor", "Zoë Ali");
  await open("Delete this student's data");
  fireEvent.change(screen.getByLabelText("Type Zoë Ali to confirm"), {
    target: { value: "zoë ALI" },
  });
  expect(awaiting(del())).toBe(false);
});

test("a blank name is never matched, not even by a blank box", async () => {
  stub(() => json(null));
  renderIt("tutor", "  ");
  await open("Delete this student's data");
  expect(awaiting(del())).toBe(true);
  fireEvent.change(screen.getByRole("textbox"), { target: { value: "   " } });
  expect(awaiting(del())).toBe(true);
});

test("pressing Enter with the wrong name sends nothing", async () => {
  const calls = stub(() => json(null));
  renderIt("tutor");
  await open("Delete this student's data");
  fireEvent.change(field(), { target: { value: "Sara" } });
  fireEvent.submit(field().closest("form")!);
  fireEvent.click(del());
  // Let any request that wrongly started reach fetch before looking.
  await new Promise((resolve) => setTimeout(resolve, 30));
  expect(posts(calls)).toHaveLength(0);
});

test("pressing Delete twice at once asks once", async () => {
  const calls = stub(({ method }) => (method === "POST" ? json(req, 202) : json(null)));
  renderIt("tutor");
  await open("Delete this student's data");
  fireEvent.change(field(), { target: { value: "Sara Ali" } });
  fireEvent.click(del());
  fireEvent.click(del());
  await screen.findByText(/will be deleted on/);
  expect(posts(calls)).toHaveLength(1);
});

test("the notice shows from the answer itself, before any refetch comes back", async () => {
  const stuck = new Promise<Response>(() => {});
  let asked = false;
  stub(({ method }) => {
    if (method === "POST") {
      asked = true;
      return json(req, 202);
    }
    return asked ? stuck : json(null);
  });
  renderIt("tutor");
  await open("Delete this student's data");
  fireEvent.change(field(), { target: { value: "Sara Ali" } });
  fireEvent.click(del());
  await screen.findByText(/will be deleted on/);
  expect(screen.queryByRole("button", { name: "Delete this student's data" })).toBeNull();
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

test("an Undo that fails says so and leaves the notice", async () => {
  stub(({ method }) => (method === "DELETE" ? json({ detail: "boom" }, 500) : json(req)));
  renderIt("tutor");
  await open("Undo");
  const alert = await screen.findByRole("alert");
  expect(alert.textContent).toBe("Couldn't do that right now. Try again.");
  expect(screen.getByRole("status").textContent).toMatch(/will be deleted on/);
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

test("a parent asks and undoes through their own child's routes", async () => {
  let pending = false;
  const calls = stub(({ method }) => {
    if (method === "POST") {
      pending = true;
      return json({ ...req, requested_role: "parent" }, 202);
    }
    if (method === "DELETE") {
      pending = false;
      return new Response(null, { status: 204 });
    }
    return json(pending ? req : null);
  });
  renderIt("parent");
  await open("Delete my child's data");
  fireEvent.change(field(), { target: { value: "Sara Ali" } });
  fireEvent.click(del());
  const note = await screen.findByRole("status");
  expect(note.textContent).toMatch(/Sara Ali's data will be deleted on .*They can't sign in/);
  await open("Undo");
  await screen.findByRole("button", { name: "Delete my child's data" });
  const writes = calls.filter((c) => c.method !== "GET");
  expect(writes.map((c) => `${c.method} ${c.path}`)).toEqual([
    "POST /api/v1/me/children/7/erasure",
    "DELETE /api/v1/me/children/7/erasure",
  ]);
});

test("focus follows the person: into the box, onto the notice, back to the button", async () => {
  let pending = false;
  stub(({ method }) => {
    if (method === "POST") {
      pending = true;
      return json(req, 202);
    }
    if (method === "DELETE") {
      pending = false;
      return new Response(null, { status: 204 });
    }
    return json(pending ? req : null);
  });
  renderIt("tutor");
  await open("Delete this student's data");
  expect(document.activeElement).toBe(field());
  fireEvent.change(field(), { target: { value: "Sara Ali" } });
  fireEvent.click(del());
  const note = await screen.findByRole("status");
  await waitFor(() => expect(document.activeElement).toBe(note));
  await open("Undo");
  const opener = await screen.findByRole("button", { name: "Delete this student's data" });
  await waitFor(() => expect(document.activeElement).toBe(opener));
});

test("Cancel returns focus to the button that opened the panel", async () => {
  stub(() => json(null));
  renderIt("tutor");
  await open("Delete this student's data");
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  const opener = await screen.findByRole("button", { name: "Delete this student's data" });
  await waitFor(() => expect(document.activeElement).toBe(opener));
});
