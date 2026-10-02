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

const SECOND = { ...LIVE, id: 4, name: "Confidence" };

type Stub = {
  rows?: unknown[];
  subjectsFail?: boolean;
  /** Answers a PATCH itself; return undefined to fall through to the default. */
  patch?: (id: number) => Promise<Response> | undefined;
};

function stub({ rows = [LIVE], subjectsFail = false, patch }: Stub = {}) {
  const calls: { method: string; url: string; body?: Record<string, unknown> }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), "http://localhost");
      const method = (init?.method ?? "GET").toUpperCase();
      const body = init?.body ? JSON.parse(String(init.body)) : undefined;
      calls.push({ method, url: url.pathname + url.search, body });
      const json = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status });
      if (url.pathname === "/api/v1/subjects")
        return subjectsFail ? json({ detail: "boom" }, 500) : json(SUBJECTS);
      if (method === "GET")
        return json(url.searchParams.get("include_archived") ? [...rows, ARCHIVED] : rows);
      if (method === "POST") return json({ ...LIVE, id: 3, ...body }, 201);
      const held = patch?.(Number(url.pathname.split("/").at(-1)));
      if (held) return held;
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
  fireEvent.change(screen.getByRole("textbox", { name: /new criterion name/i }), {
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

test("Enter in the edit row saves what was typed, and Cancel does not submit", async () => {
  const calls = stub();
  renderSetting();
  const row = (await screen.findByText("Exam technique")).closest("li")!;
  fireEvent.click(within(row).getByRole("button", { name: /edit/i }));
  const name = within(row).getByRole("textbox", { name: /^name/i });
  fireEvent.change(name, { target: { value: "Technique" } });

  const form = name.closest("form")!;
  // A form inside the create form would be invalid HTML and submit the wrong one.
  expect(form.parentElement!.closest("form")).toBeNull();
  expect((within(row).getByRole("button", { name: /cancel/i }) as HTMLButtonElement).type).toBe(
    "button",
  );
  fireEvent.submit(form);

  await waitFor(() => expect(calls.some((c) => c.method === "PATCH")).toBe(true));
  expect(calls.find((c) => c.method === "PATCH")!.body).toEqual({
    name: "Technique",
    description: null,
  });
  // Only the rename was sent: the create form did not fire.
  expect(calls.some((c) => c.method === "POST")).toBe(false);
});

test("Enter on a blank name saves nothing", async () => {
  const calls = stub();
  renderSetting();
  const row = (await screen.findByText("Exam technique")).closest("li")!;
  fireEvent.click(within(row).getByRole("button", { name: /edit/i }));
  const name = within(row).getByRole("textbox", { name: /^name/i });
  fireEvent.change(name, { target: { value: "   " } });
  fireEvent.submit(name.closest("form")!);
  await Promise.resolve();
  expect(calls.some((c) => c.method === "PATCH")).toBe(false);
});

/** Opens both rows for editing and saves the first, then the second, with the
    first row's PATCH held open until the caller releases it. */
async function saveBothFirstHeld() {
  let release!: (r: Response) => void;
  const held = new Promise<Response>((resolve) => (release = resolve));
  const calls = stub({ rows: [LIVE, SECOND], patch: (id) => (id === 1 ? held : undefined) });
  renderSetting();
  const first = (await screen.findByText("Exam technique")).closest("li")!;
  const second = screen.getByText("Confidence").closest("li")!;
  for (const row of [first, second]) {
    fireEvent.click(within(row).getByRole("button", { name: /edit/i }));
    fireEvent.change(within(row).getByRole("textbox", { name: /^name/i }), {
      target: { value: "Renamed" },
    });
    fireEvent.click(within(row).getByRole("button", { name: /save/i }));
  }
  // The second row's save has landed and closed while the first is still out.
  await waitFor(() => expect(within(second).queryByRole("textbox")).toBeNull());
  expect(calls.filter((c) => c.method === "PATCH")).toHaveLength(2);
  return { first, second, release };
}

test("two rows saved back to back both close, the first returning last", async () => {
  const { first, release } = await saveBothFirstHeld();
  // Still in flight: the first row stays busy, so Enter cannot send it twice.
  expect((within(first).getByRole("button", { name: /save/i }) as HTMLButtonElement).disabled).toBe(
    true,
  );
  release(new Response(JSON.stringify({ ...LIVE, name: "Renamed" }), { status: 200 }));
  await waitFor(() => expect(within(first).queryByRole("textbox")).toBeNull());
});

test("a save that fails after a later row's save succeeds is shown on its own row", async () => {
  const { first, second, release } = await saveBothFirstHeld();
  release(new Response(JSON.stringify({ detail: "That name is taken." }), { status: 409 }));
  expect((await within(first).findByRole("alert")).textContent).toMatch(/name is taken/i);
  // What was typed is kept, and the other row is not blamed.
  expect((within(first).getByRole("textbox", { name: /^name/i }) as HTMLInputElement).value).toBe(
    "Renamed",
  );
  expect(within(second).queryByRole("alert")).toBeNull();
});

test("subjects that fail to load are reported, and nothing can be added", async () => {
  stub({ subjectsFail: true });
  renderSetting();
  expect((await screen.findByRole("alert")).textContent).toMatch(/subjects/i);
  fireEvent.change(screen.getByRole("textbox", { name: /new criterion name/i }), {
    target: { value: "Practicals" },
  });
  // Otherwise the only scope on offer is "All subjects", and it is permanent.
  expect(
    (screen.getByRole("button", { name: /add criterion/i }) as HTMLButtonElement).disabled,
  ).toBe(true);
});

test("Add waits for the subjects to load", async () => {
  stub();
  renderSetting();
  fireEvent.change(screen.getByRole("textbox", { name: /new criterion name/i }), {
    target: { value: "Practicals" },
  });
  const add = screen.getByRole("button", { name: /add criterion/i }) as HTMLButtonElement;
  expect(add.disabled).toBe(true);
  await screen.findByRole("option", { name: /chemistry/i });
  expect(add.disabled).toBe(false);
});
