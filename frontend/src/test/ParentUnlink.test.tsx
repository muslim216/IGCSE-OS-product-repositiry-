import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, test, vi } from "vitest";
import LinkedParents from "../components/LinkedParents";
import ParentDashboard from "../parent/ParentDashboard";

/* Removing a parent's access has to end it for real: the tutor and the student
   are asked first, a refusal is shown, and a parent who stops following a child
   never causes another request for that child. */

const PARENT = { id: 5, parent_id: 9, name: "Mona", email: "mona@example.com", linked_at: "x" };

function respondWith(handler: (url: string, method: string) => Response | undefined) {
  const calls: { url: string; method: string }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      calls.push({ url, method });
      return handler(url, method) ?? new Response("[]", { status: 200 });
    }),
  );
  return calls;
}

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

function renderIn(ui: React.ReactElement) {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

// --- LinkedParents -----------------------------------------------------------

test("the tutor confirms before a parent is removed, then the link is deleted", async () => {
  const calls = respondWith((url, method) => {
    if (method === "DELETE") return new Response(null, { status: 204 });
    if (url.endsWith("/students/3/parents")) return json([PARENT]);
  });
  renderIn(<LinkedParents studentId={3} />);

  fireEvent.click(await screen.findByRole("button", { name: "Remove Mona" }));
  expect(calls.some((c) => c.method === "DELETE")).toBe(false);
  fireEvent.click(screen.getByRole("button", { name: "Remove" }));

  await waitFor(() =>
    expect(calls).toContainEqual({ url: "/api/v1/students/3/parents/5", method: "DELETE" }),
  );
});

test("cancelling leaves the parent linked", async () => {
  const calls = respondWith((url) => (url.endsWith("/parents") ? json([PARENT]) : undefined));
  renderIn(<LinkedParents studentId={3} />);

  fireEvent.click(await screen.findByRole("button", { name: "Remove Mona" }));
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

  expect(calls.some((c) => c.method === "DELETE")).toBe(false);
  expect(screen.getByRole("button", { name: "Remove Mona" })).toBeInTheDocument();
});

test("a refused removal is said in the dialog", async () => {
  respondWith((url, method) => {
    if (method === "DELETE") return json({ detail: "Link not found" }, 404);
    if (url.endsWith("/parents")) return json([PARENT]);
  });
  renderIn(<LinkedParents studentId={3} />);

  fireEvent.click(await screen.findByRole("button", { name: "Remove Mona" }));
  fireEvent.click(screen.getByRole("button", { name: "Remove" }));

  expect(await screen.findByRole("alert")).toBeInTheDocument();
});

test("the student's own view talks about their marks, not this child's", async () => {
  respondWith((url) => (url.endsWith("/me/parent-links") ? json([PARENT]) : undefined));
  renderIn(<LinkedParents />);

  fireEvent.click(await screen.findByRole("button", { name: "Remove Mona" }));
  expect(screen.getByText(/see your marks/)).toBeInTheDocument();
  expect(screen.getByText(/seeing your marks/)).toBeInTheDocument();
  expect(screen.queryByText(/this child's/)).not.toBeInTheDocument();
});

// --- Stop following ------------------------------------------------------------

const SARA = { id: 2, name: "Sara", role: "student" };
const SAM = { id: 3, name: "Sam", role: "student" };

function dashboardFetch(children: unknown[], opts: { readinessFails?: boolean } = {}) {
  let list = children;
  return respondWith((url, method) => {
    if (method === "DELETE" && url.includes("/me/children/")) {
      const id = Number(url.split("/").pop());
      list = list.filter((c) => (c as { id: number }).id !== id);
      return new Response(null, { status: 204 });
    }
    if (url.includes("/me/children")) return json(list);
    if (url.includes("/readiness/students/")) {
      if (opts.readinessFails) return json({ detail: "boom" }, 500);
      const id = Number(url.split("/").pop());
      const name = id === 2 ? "Sara" : "Sam";
      return json({ student_id: id, student_name: name, subjects: [] });
    }
    if (url.includes("/narrative")) {
      return json({ text: null, generated_at: null, prompt_version: null });
    }
    if (url.includes("/attendance")) {
      return json({ lessons: 0, present: 0, absent: 0, not_taken: 0, rate: null, classes: [] });
    }
  });
}

async function stopFollowing() {
  fireEvent.click(await screen.findByRole("button", { name: "Stop following this child" }));
  fireEvent.click(screen.getByRole("button", { name: "Stop following" }));
}

test("stopping the first of two children moves to the other and never asks for the first again", async () => {
  const calls = dashboardFetch([SARA, SAM]);
  renderIn(<ParentDashboard />);

  await stopFollowing();

  expect(await screen.findByText(/stopped following Sara/)).toHaveAttribute("role", "status");
  await screen.findByText(/Sam/);
  const after = calls.length;
  await new Promise((r) => setTimeout(r, 50));
  const later = calls.slice(calls.findIndex((c) => c.method === "DELETE") + 1);
  expect(later.filter((c) => /\/(2)(\/|$|\?)|student_id=2\b/.test(c.url))).toEqual([]);
  expect(calls.length).toBeGreaterThanOrEqual(after);
  expect(document.activeElement?.tagName).toBe("H1");
});

test("stopping the only child says so rather than landing silently on the empty state", async () => {
  const calls = dashboardFetch([SARA]);
  renderIn(<ParentDashboard />);

  await stopFollowing();

  expect(await screen.findByText(/stopped following Sara/)).toHaveAttribute("role", "status");
  expect(screen.getByText("No child is linked to this account yet.")).toBeInTheDocument();
  await new Promise((r) => setTimeout(r, 50));
  const later = calls.slice(calls.findIndex((c) => c.method === "DELETE") + 1);
  expect(later.filter((c) => /\/2(\/|$|\?)|student_id=2\b/.test(c.url))).toEqual([]);
  expect(document.activeElement?.tagName).toBe("H1");
});

test("cancelling the confirm changes nothing", async () => {
  const calls = dashboardFetch([SARA]);
  renderIn(<ParentDashboard />);

  fireEvent.click(await screen.findByRole("button", { name: "Stop following this child" }));
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

  expect(calls.some((c) => c.method === "DELETE")).toBe(false);
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
});

test("a failed removal is shown and the child stays", async () => {
  respondWith((url, method) => {
    if (method === "DELETE") return json({ detail: "nope" }, 500);
    if (url.includes("/me/children")) return json([SARA]);
    if (url.includes("/readiness/students/")) {
      return json({ student_id: 2, student_name: "Sara", subjects: [] });
    }
  });
  renderIn(<ParentDashboard />);

  await stopFollowing();

  expect(await screen.findByRole("alert")).toBeInTheDocument();
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
});

test("the button is there even when the child's readiness fails to load", async () => {
  dashboardFetch([SARA], { readinessFails: true });
  renderIn(<ParentDashboard />);

  expect(
    await screen.findByRole("button", { name: "Stop following this child" }),
  ).toBeInTheDocument();
});
