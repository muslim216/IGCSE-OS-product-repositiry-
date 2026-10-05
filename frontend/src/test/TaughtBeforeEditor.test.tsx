import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import TaughtBeforeEditor, { buildGroups } from "../tutor/TaughtBeforeEditor";

/* "Where is this class up to?" (9.1d). */

const TOPICS = [
  { id: 1, chapter_id: 10, code: "1", title: "Forces", parent_id: null, weight: 1 },
  { id: 2, chapter_id: 10, code: "1.1", title: "Speed", parent_id: 1, weight: 1 },
  { id: 3, chapter_id: 10, code: "1.2", title: "Momentum", parent_id: 1, weight: 1 },
  { id: 4, chapter_id: 11, code: "2", title: "Waves", parent_id: null, weight: 1 },
  { id: 5, chapter_id: 11, code: "2.1", title: "Sound", parent_id: 4, weight: 1 },
];

let answer: { answered: boolean; answered_at: string | null; topic_ids: number[] };
let topics: unknown[];
let puts: unknown[];
const CHAPTERS = [
  { id: 10, code: "1", title: "Forces", position: 0 },
  { id: 11, code: "2", title: "Waves", position: 1 },
];
let failPut: boolean;
let requested: string[];

beforeEach(() => {
  answer = { answered: false, answered_at: null, topic_ids: [] };
  topics = TOPICS;
  puts = [];
  failPut = false;
  requested = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = new URL(String(input), "http://localhost").pathname;
      requested.push(path);
      const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200 });
      if (path === "/api/v1/subjects/7/topics") return json(topics);
      if (path === "/api/v1/subjects/7/chapters") return json(CHAPTERS);
      if (path === "/api/v1/groups/3/taught-before") {
        if (init?.method === "PUT") {
          puts.push(JSON.parse(String(init.body)));
          if (failPut) return new Response("{}", { status: 500 });
          const ids = (JSON.parse(String(init.body)) as { topic_ids: number[] }).topic_ids;
          answer = { answered: true, answered_at: "2026-10-05T10:00:00Z", topic_ids: ids };
        }
        return json(answer);
      }
      return json([]);
    }),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function renderEditor() {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter>
        <TaughtBeforeEditor groupId={3} subjectId={7} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const buttons = (name: string) => screen.getAllByRole("button", { name });
const box = (name: string) => screen.getByRole("checkbox", { name }) as HTMLInputElement;

test("says it is not answered yet, and that the answer is the tutor's own", async () => {
  renderEditor();
  expect(await screen.findByText("Not answered yet.")).toBeInTheDocument();
  expect(screen.getByText(/declaring this yourself/)).toBeInTheDocument();
});

test("ticking a chapter ticks its topics, and a partial one shows as mixed", async () => {
  renderEditor();
  const forces = await screen.findByRole("group", { name: /Forces/ });
  const all = within(forces).getByRole("checkbox", {
    name: /All topics in 1 Forces/,
  }) as HTMLInputElement;
  expect(all.checked).toBe(false);
  expect(all.indeterminate).toBe(false);

  fireEvent.click(box("1.1 Speed"));
  expect(all.indeterminate).toBe(true);
  expect(all.checked).toBe(false);

  fireEvent.click(all);
  expect(all.checked).toBe(true);
  expect(all.indeterminate).toBe(false);
  for (const name of ["1 Forces", "1.1 Speed", "1.2 Momentum"])
    expect(box(name).checked).toBe(true);
  // Another group is untouched.
  expect(box("2.1 Sound").checked).toBe(false);

  fireEvent.click(all);
  expect(box("1.2 Momentum").checked).toBe(false);
});

test("Save sends the ticked ids and the summary shows the answer", async () => {
  renderEditor();
  await screen.findByText("Not answered yet.");
  fireEvent.click(box("1.1 Speed"));
  fireEvent.click(box("2.1 Sound"));
  fireEvent.click(buttons("Save")[1]);
  await waitFor(() => expect(puts).toEqual([{ topic_ids: [2, 5] }]));
  expect(await screen.findByText(/2 topics ticked/)).toBeInTheDocument();
  expect(screen.getByText(/^You answered/)).toBeInTheDocument();
});

test("Starting fresh saves an empty list", async () => {
  renderEditor();
  await screen.findByText("Not answered yet.");
  fireEvent.click(box("1.1 Speed"));
  fireEvent.click(buttons("Starting fresh")[1]);
  await waitFor(() => expect(puts).toEqual([{ topic_ids: [] }]));
  expect(await screen.findByText(/nothing taught before Avora/)).toBeInTheDocument();
  expect(box("1.1 Speed").checked).toBe(false);
});

test("an existing answer is shown ticked and stays editable", async () => {
  answer = { answered: true, answered_at: "2026-10-01T10:00:00Z", topic_ids: [2] };
  renderEditor();
  expect(await screen.findByText(/1 topic ticked/)).toBeInTheDocument();
  expect(box("1.1 Speed").checked).toBe(true);
  expect(box("1.2 Momentum").checked).toBe(false);
});

test("a failed save keeps the ticks and shows the error", async () => {
  failPut = true;
  renderEditor();
  await screen.findByText("Not answered yet.");
  fireEvent.click(box("1.2 Momentum"));
  fireEvent.click(buttons("Save")[1]);
  expect(await screen.findByText(/went wrong/i)).toBeInTheDocument();
  expect(box("1.2 Momentum").checked).toBe(true);
  expect(screen.getByText("Not saved yet: 1 topic ticked.")).toBeInTheDocument();
  expect(buttons("Save")[1]).toBeEnabled();
});

test("a subject with no topics points to its syllabus and offers no checkboxes", async () => {
  topics = [];
  renderEditor();
  const link = await screen.findByRole("link", { name: /Add the syllabus in Subject setup/ });
  expect(link).toHaveAttribute("href", "/tutor/subject-setup?subject=7#syllabus");
  expect(screen.queryAllByRole("checkbox")).toHaveLength(0);
  expect(screen.queryByRole("button", { name: "Save" })).not.toBeInTheDocument();
});

test("groups are chapters in teaching order, with unfiled topics last under their own heading", () => {
  const groups = buildGroups(
    [
      { id: 5, chapter_id: 11, code: "2.1", title: "Sound", parent_id: null, weight: 1 },
      { id: 2, chapter_id: 10, code: "1.1", title: "Speed", parent_id: null, weight: 1 },
      { id: 9, chapter_id: null, code: "X", title: "Practical skills", parent_id: null, weight: 1 },
    ],
    CHAPTERS,
  );
  expect(groups.map((g) => [g.title, g.rows.map((r) => r.topic.id)])).toEqual([
    ["Forces", [2]],
    ["Waves", [5]],
    ["Topics not filed under a chapter", [9]],
  ]);
});

test("a subject with no chapters is one plain group, and a chapter with no topics is left out", () => {
  const topic = {
    id: 2,
    chapter_id: null,
    code: "1.1",
    title: "Speed",
    parent_id: null,
    weight: 1,
  };
  expect(buildGroups([topic], []).map((g) => g.title)).toEqual(["Topics"]);
  expect(buildGroups([{ ...topic, chapter_id: 10 }], CHAPTERS).map((g) => g.title)).toEqual([
    "Forces",
  ]);
});

test("unsaved ticks are called unsaved, and Discard puts the saved list back", async () => {
  answer = { answered: true, answered_at: "2026-10-01T10:00:00Z", topic_ids: [2] };
  renderEditor();
  await screen.findByText(/1 topic ticked/);
  expect(screen.queryByRole("button", { name: "Discard changes" })).not.toBeInTheDocument();
  fireEvent.click(box("2.1 Sound"));
  expect(screen.getByText("Not saved yet: 2 topics ticked.")).toBeInTheDocument();
  fireEvent.click(buttons("Discard changes")[0]);
  expect(box("2.1 Sound").checked).toBe(false);
  expect(screen.getByText(/1 topic ticked/)).toBeInTheDocument();
});

test("leaving with unsaved ticks asks the browser to confirm, and not otherwise", async () => {
  renderEditor();
  await screen.findByText("Not answered yet.");
  const leave = () => {
    const event = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(event);
    return event.defaultPrevented;
  };
  expect(leave()).toBe(false);
  fireEvent.click(box("1.1 Speed"));
  expect(leave()).toBe(true);
  fireEvent.click(buttons("Discard changes")[0]);
  expect(leave()).toBe(false);
});

test("Starting fresh on a saved list asks first, and saves only on confirm", async () => {
  answer = { answered: true, answered_at: "2026-10-01T10:00:00Z", topic_ids: [2, 3] };
  renderEditor();
  await screen.findByText(/2 topics ticked/);
  fireEvent.click(buttons("Starting fresh")[1]);
  const dialog = await screen.findByRole("dialog", { name: "Clear 2 saved topics?" });
  expect(
    within(dialog).getByText("This saves that nothing was taught before Avora."),
  ).toBeVisible();
  expect(puts).toEqual([]);

  fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  expect(puts).toEqual([]);

  fireEvent.click(buttons("Starting fresh")[1]);
  fireEvent.click(await screen.findByRole("button", { name: "Clear and save" }));
  await waitFor(() => expect(puts).toEqual([{ topic_ids: [] }]));
});

test("the action row above the list saves the same ticks", async () => {
  renderEditor();
  await screen.findByText("Not answered yet.");
  expect(screen.getByText("0 of 5 ticked")).toBeInTheDocument();
  fireEvent.click(box("2.1 Sound"));
  expect(screen.getByText("1 of 5 ticked")).toBeInTheDocument();
  fireEvent.click(buttons("Save")[0]);
  await waitFor(() => expect(puts).toEqual([{ topic_ids: [5] }]));
});

test("a parent with only its children ticked shows the chapter as mixed", async () => {
  renderEditor();
  await screen.findByText("Not answered yet.");
  const all = screen.getByRole("checkbox", { name: "All topics in 1 Forces" }) as HTMLInputElement;
  fireEvent.click(box("1.1 Speed"));
  fireEvent.click(box("1.2 Momentum"));
  expect(box("1 Forces").checked).toBe(false);
  expect(all.indeterminate).toBe(true);
  fireEvent.click(buttons("Save")[1]);
  await waitFor(() => expect(puts).toEqual([{ topic_ids: [2, 3] }]));
});

test("children are nested inside their parent's list item", async () => {
  renderEditor();
  await screen.findByText("Not answered yet.");
  const parent = box("1 Forces").closest("li")!;
  expect(within(parent).getByRole("checkbox", { name: "1.1 Speed" })).toBeInTheDocument();
  expect(within(parent).getAllByRole("list")).toHaveLength(1);
});

test("a chapters failure still shows the topics, as one flat group, with a note", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const path = new URL(String(input), "http://localhost").pathname;
      const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200 });
      if (path === "/api/v1/subjects/7/topics") return json(TOPICS);
      if (path === "/api/v1/subjects/7/chapters") return new Response("{}", { status: 500 });
      return json(answer);
    }),
  );
  renderEditor();
  expect(
    await screen.findByText("Chapters couldn't be loaded, so topics aren't grouped by chapter."),
  ).toBeInTheDocument();
  expect(screen.getAllByRole("group")).toHaveLength(1);
  expect(box("2.1 Sound")).toBeInTheDocument();
});

test("an id no longer in the topic list is not sent", async () => {
  answer = { answered: true, answered_at: "2026-10-01T10:00:00Z", topic_ids: [2, 999] };
  renderEditor();
  await screen.findByText(/2 topics ticked/);
  fireEvent.click(box("2.1 Sound"));
  fireEvent.click(buttons("Save")[1]);
  await waitFor(() => expect(puts).toEqual([{ topic_ids: [2, 5] }]));
});

test("a refetch of the saved answer does not overwrite unsaved ticks", async () => {
  renderEditor();
  await screen.findByText("Not answered yet.");
  fireEvent.click(box("1.1 Speed"));
  const reads = () => requested.filter((p) => p === "/api/v1/groups/3/taught-before").length;
  const before = reads();
  answer = { answered: true, answered_at: "2026-10-01T10:00:00Z", topic_ids: [5] };
  window.dispatchEvent(new Event("visibilitychange"));
  await waitFor(() => expect(reads()).toBeGreaterThan(before));
  expect(box("1.1 Speed").checked).toBe(true);
  expect(box("2.1 Sound").checked).toBe(false);
});
