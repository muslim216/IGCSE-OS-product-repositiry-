import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, test, vi } from "vitest";
import DownloadChildData from "../components/DownloadChildData";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function renderIt(asker: "tutor" | "parent") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <DownloadChildData asker={asker} studentId={7} />
    </QueryClientProvider>,
  );
}

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
const ready = { id: 3, status: "ready", expires_at: "2026-11-01T00:00:00Z", error: null };
const asked = () => screen.getByRole("button", { name: "Download this child's data" });

test("a tutor asks, the file is fetched from the student route and saved once", async () => {
  const calls: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push(`${init?.method ?? "GET"} ${new URL(url, "http://localhost").pathname}`);
      if (url.endsWith("/file")) return new Response(new Blob(["zip"]));
      if (init?.method === "POST") return json({ ...ready, status: "pending" }, 202);
      return json(ready);
    }),
  );
  URL.createObjectURL = vi.fn(() => "blob:zip");
  URL.revokeObjectURL = vi.fn();
  const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  renderIt("tutor");
  fireEvent.click(asked());
  await screen.findByText(/Downloaded/);
  expect(calls).toEqual([
    "POST /api/v1/students/7/export",
    "GET /api/v1/students/7/export/3",
    "GET /api/v1/students/7/export/3/file",
  ]);
  expect(click).toHaveBeenCalledTimes(1);
});

test("a parent uses their own child's routes and sees a failed build said plainly", async () => {
  const calls: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push(`${init?.method ?? "GET"} ${new URL(url, "http://localhost").pathname}`);
      const body = { ...ready, status: "failed", error: "The export could not be built." };
      return json(body, init?.method === "POST" ? 202 : 200);
    }),
  );
  renderIt("parent");
  fireEvent.click(asked());
  await screen.findByText("The export could not be built.");
  expect(calls).toEqual([
    "POST /api/v1/me/children/7/export",
    "GET /api/v1/me/children/7/export/3",
  ]);
});

test("a refused request shows the error and lets them try again", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => json({ detail: "Student not found" }, 404)),
  );
  renderIt("tutor");
  fireEvent.click(asked());
  await waitFor(() => expect(screen.getByText(/We couldn.t find that/)).toBeTruthy());
  expect((asked() as HTMLButtonElement).disabled).toBe(false);
});
