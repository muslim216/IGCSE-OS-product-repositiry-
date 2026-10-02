import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, test, vi } from "vitest";
import CustomCriteriaSetting from "../tutor/CustomCriteriaSetting";

/* Managing tutor-defined criteria (task 5.4c over 5.4b's API): create with an
   optional subject that is fixed from then on, rename, and archive. */

const SUBJECTS = [
  { id: 7, exam_board: "Edexcel IGCSE", code: "4CH1", name: "Chemistry", grade_scale: "9-1" },
];

const LIVE = {
  id: 1,
  name: "Exam technique",
  description: null,
  subject_id: null,
  archived_at: null,
  created_by_id: 1,
  created_at: "2026-09-20T10:00:00Z",
};
const ARCHIVED = {
  ...LIVE,
  id: 2,
  name: "Old one",
  subject_id: 7,
  archived_at: "2026-09-21T10:00:00Z",
};

function stub() {
  const calls: { method: string; url: string; body?: Record<string, unknown> }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), "http://localhost");
      const method = (init?.method ?? "GET").toUpperCase();
      const body = init?.body ? JSON.parse(String(init.body)) : undefined;
      calls.push({ method, url: url.pathname + url.search, body });
      const json = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status });
      if (url.pathname === "/api/v1/subjects") return json(SUBJECTS);
      if (method === "GET")
        return json(url.searchParams.get("include_archived") ? [LIVE, ARCHIVED] : [LIVE]);
      if (method === "POST") return json({ ...LIVE, id: 3, ...body }, 201);
      return json({ ...LIVE, ...body });
    }),
  );
  return calls;
}

function renderSetting() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <CustomCriteriaSetting />
    </QueryClientProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

test("creates a criterion for one subject", async () => {
  const calls = stub();
  renderSetting();
  await screen.findByRole("option", { name: /chemistry/i });
  fireEvent.change(screen.getByRole("textbox", { name: /criterion name/i }), {
    target: { value: "Practicals" },
  });
  fireEvent.change(screen.getByRole("combobox", { name: /applies to/i }), {
    target: { value: "7" },
  });
  fireEvent.click(screen.getByRole("button", { name: /add criterion/i }));

  await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
  expect(calls.find((c) => c.method === "POST")!.body).toEqual({
    name: "Practicals",
    description: null,
    subject_id: 7,
  });
});

test("archived criteria are hidden until asked for, and can be unarchived", async () => {
  const calls = stub();
  renderSetting();
  await screen.findByText("Exam technique");
  expect(screen.queryByText("Old one")).toBeNull();

  fireEvent.click(screen.getByRole("checkbox", { name: /show archived/i }));
  const row = (await screen.findByText("Old one")).closest("li")!;
  fireEvent.click(within(row).getByRole("button", { name: /unarchive/i }));

  await waitFor(() =>
    expect(calls.some((c) => c.method === "PATCH" && c.url === "/api/v1/custom-criteria/2")).toBe(
      true,
    ),
  );
  expect(calls.find((c) => c.method === "PATCH")!.body).toEqual({ archived: false });
});

test("archiving and renaming send a PATCH", async () => {
  const calls = stub();
  renderSetting();
  const row = (await screen.findByText("Exam technique")).closest("li")!;
  fireEvent.click(within(row).getByRole("button", { name: /^archive/i }));
  await waitFor(() => expect(calls.some((c) => c.method === "PATCH")).toBe(true));
  expect(calls.find((c) => c.method === "PATCH")!.body).toEqual({ archived: true });

  fireEvent.click(within(row).getByRole("button", { name: /edit/i }));
  fireEvent.change(within(row).getByRole("textbox", { name: /^name/i }), {
    target: { value: "Technique" },
  });
  fireEvent.click(within(row).getByRole("button", { name: /save/i }));
  await waitFor(() =>
    expect(calls.filter((c) => c.method === "PATCH").at(-1)!.body).toEqual({
      name: "Technique",
      description: null,
    }),
  );
});
