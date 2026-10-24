import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import DownloadChildData from "../components/DownloadChildData";

let click: ReturnType<typeof vi.spyOn>;
beforeEach(() => {
  URL.createObjectURL = vi.fn(() => "blob:zip");
  URL.revokeObjectURL = vi.fn();
  click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function renderIt(asker: "tutor" | "parent") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <DownloadChildData asker={asker} studentId={7} name="Sara" pollMs={10} />
    </QueryClientProvider>,
  );
}

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
const exp = (status: string, error: string | null = null) => ({
  id: 3,
  status,
  expires_at: "2026-11-01T00:00:00Z",
  error,
});
const prepare = () => screen.getByRole("button", { name: "Request Sara's data" });
const save = () => screen.findByRole("button", { name: "Download Sara's data (ZIP)" });

type Handler = (path: string, method: string) => Response;
function stub(handler: Handler) {
  const calls: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      const path = new URL(url, "http://localhost").pathname;
      calls.push(`${method} ${path}`);
      return handler(path, method);
    }),
  );
  return calls;
}

test("a tutor asks, waits while it is built, then saves it with a press", async () => {
  let polls = 0;
  const calls = stub((path, method) => {
    if (path.endsWith("/file")) return new Response(new Blob(["zip"]));
    if (method === "POST") return json(exp("pending"), 202);
    polls += 1;
    return json(exp(polls < 3 ? "running" : "ready"));
  });
  renderIt("tutor");
  fireEvent.click(prepare());
  expect(await screen.findByText(/Preparing the file/)).toBeTruthy();
  // Nothing is saved by itself: only a press does that.
  fireEvent.click(await save());
  await screen.findByText(/Downloaded/);
  expect(calls[0]).toBe("POST /api/v1/students/7/export");
  expect(calls.filter((c) => c === "GET /api/v1/students/7/export/3").length).toBe(3);
  expect(calls.at(-1)).toBe("GET /api/v1/students/7/export/3/file");
  expect(click).toHaveBeenCalledTimes(1);
  await waitFor(() => expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:zip"), {
    timeout: 3000,
  });
});

test("polling stops once it is ready", async () => {
  const calls = stub((path, method) =>
    method === "POST" ? json(exp("pending"), 202) : json(exp(path ? "ready" : "ready")),
  );
  renderIt("tutor");
  fireEvent.click(prepare());
  await save();
  const seen = calls.length;
  await new Promise((r) => setTimeout(r, 80));
  expect(calls.length).toBe(seen);
});

test("pressing twice asks once", async () => {
  const calls = stub((_p, method) =>
    method === "POST" ? json(exp("pending"), 202) : json(exp("running")),
  );
  renderIt("tutor");
  fireEvent.click(prepare());
  fireEvent.click(prepare());
  await screen.findByText(/Preparing the file/);
  expect(calls.filter((c) => c.startsWith("POST")).length).toBe(1);
});

test("a parent uses their own child's routes and a failed build is said plainly", async () => {
  const calls = stub((_p, method) =>
    json(exp("failed", "The export could not be built."), method === "POST" ? 202 : 200),
  );
  renderIt("parent");
  fireEvent.click(prepare());
  const alert = await screen.findByRole("alert");
  expect(alert.textContent).toBe("The export could not be built.");
  expect(calls.slice(0, 2)).toEqual([
    "POST /api/v1/me/children/7/export",
    "GET /api/v1/me/children/7/export/3",
  ]);
});

test("a file that has expired says so", async () => {
  stub((path, method) => {
    if (path.endsWith("/file")) return json({ detail: "This export has expired." }, 410);
    return method === "POST" ? json(exp("ready"), 202) : json(exp("ready"));
  });
  renderIt("tutor");
  fireEvent.click(prepare());
  fireEvent.click(await save());
  const alert = await screen.findByRole("alert");
  expect(alert.textContent).toBe("That file has expired; request a new one.");
  expect(URL.revokeObjectURL).not.toHaveBeenCalled();
});

test("a refused request shows the error and can be tried again", async () => {
  stub(() => json({ detail: "Student not found" }, 404));
  renderIt("tutor");
  fireEvent.click(prepare());
  await waitFor(() => expect(screen.getByRole("alert").textContent).toMatch(/couldn.t find that/));
  expect(prepare().getAttribute("aria-disabled")).toBe("false");
});

test("a network failure shows a plain message", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => {
      throw new TypeError("Failed to fetch");
    }),
  );
  renderIt("tutor");
  fireEvent.click(prepare());
  const alert = await screen.findByRole("alert");
  expect(alert.textContent).not.toMatch(/Failed to fetch/);
});

test("the button keeps focus while the file is prepared", async () => {
  stub((_p, method) => (method === "POST" ? json(exp("pending"), 202) : json(exp("running"))));
  renderIt("tutor");
  prepare().focus();
  fireEvent.click(prepare());
  await screen.findByText(/Preparing the file/);
  expect(document.activeElement).toBe(prepare());
});
