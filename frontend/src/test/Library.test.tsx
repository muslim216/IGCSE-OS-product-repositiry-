import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, test, vi } from "vitest";
import LibraryPage from "../tutor/LibraryPage";
import { GroupResourcesPanel } from "../tutor/GroupResourcesPanel";

/* The Library is a record of the tutor's teaching material (9.3b): classifieds,
   then files, then recordings. What has to hold: each section stands alone (one
   failing leaves the others), files open through the authenticated helper and
   recordings only as safe external links, and nothing here edits anything. */

const SUBJECTS = [
  { id: 7, exam_board: "Edexcel IGCSE", code: "4CH1", name: "Chemistry", grade_scale: "9-1" },
  { id: 8, exam_board: "Edexcel IGCSE", code: "4PH1", name: "Physics", grade_scale: "9-1" },
];
const CHAPTERS = [
  { id: 21, code: "2", title: "Bonding", position: 1 },
  { id: 22, code: "1", title: "States of matter", position: 2 },
];
const classified = (over: object) => ({
  id: 1,
  subject_id: 7,
  title: "Bonding set",
  file_name: "b.pdf",
  mark_scheme_name: null,
  chapter_id: 21,
  notes: "",
  created_at: "2026-09-20T10:00:00Z",
  ...over,
});
const CLASSIFIEDS = [
  classified({ id: 1, title: "Bonding set", mark_scheme_name: "ms.pdf" }),
  classified({ id: 2, title: "States set", chapter_id: 22 }),
  classified({ id: 3, title: "Forces set", subject_id: 8, chapter_id: null }),
];
const resource = (over: object) => ({
  id: 10,
  group_id: 1,
  group_name: "Chem Y10",
  kind: "file",
  title: "Moles worksheet",
  url: null,
  file_name: "moles.pdf",
  created_at: "2026-09-21T10:00:00Z",
  ...over,
});
const FILES = [
  resource({ id: 10 }),
  resource({ id: 11, group_id: 2, group_name: "Phys Y11", title: "Forces sheet" }),
];
const RECORDINGS = [
  resource({
    id: 20,
    kind: "recording",
    title: "Lesson 4",
    url: "https://example.com/rec",
    file_name: null,
  }),
  resource({
    id: 21,
    kind: "recording",
    title: "Sneaky",
    url: "javascript:alert(1)",
    file_name: null,
  }),
];

interface Stub {
  classifieds?: unknown[] | "fail";
  files?: unknown[] | "fail";
  recordings?: unknown[] | "fail";
  subjects?: unknown[] | "fail";
  chapters?: unknown[] | "fail";
}

function stub(s: Stub = {}) {
  const {
    classifieds = CLASSIFIEDS,
    files = FILES,
    recordings = RECORDINGS,
    subjects = SUBJECTS,
    chapters = CHAPTERS,
  } = s;
  const calls: { method: string; path: string; headers: HeadersInit | undefined }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), "http://localhost");
      const path = url.pathname;
      calls.push({ method: (init?.method ?? "GET").toUpperCase(), path, headers: init?.headers });
      const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200 });
      const serve = (v: unknown[] | "fail") =>
        v === "fail" ? new Response(JSON.stringify({ detail: "boom" }), { status: 500 }) : json(v);
      if (path === "/api/v1/classifieds") return serve(classifieds);
      if (path === "/api/v1/resources")
        return serve(url.searchParams.get("kind") === "recording" ? recordings : files);
      if (path === "/api/v1/subjects") return serve(subjects);
      if (path === "/api/v1/subjects/7/chapters") return serve(chapters);
      if (path === "/api/v1/subjects/8/chapters") return json([]);
      if (path.endsWith("/file") || path.endsWith("/mark-scheme"))
        return new Response("%PDF", { status: 200 });
      return json([]);
    }),
  );
  return calls;
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <LibraryPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return client;
}

const CONTROLS = /add|remove|delete|edit|upload|save/i;

const section = (name: string) =>
  screen.getByRole("heading", { level: 2, name }).closest("section") as HTMLElement;

afterEach(() => vi.unstubAllGlobals());

test("three sections in order, material grouped by subject, chapter and class", async () => {
  stub();
  renderPage();
  await screen.findByText("Bonding set");

  const headings = screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent);
  expect(headings).toEqual(["Classifieds", "Files", "Recordings"]);

  const cls = within(section("Classifieds"));
  expect(cls.getByRole("heading", { level: 3, name: "Chemistry" })).toBeInTheDocument();
  expect(cls.getByRole("heading", { level: 3, name: "Physics" })).toBeInTheDocument();
  // Chapters in teaching order, each classified under its own.
  await cls.findByText("2 Bonding");
  expect(cls.getByText("1 States of matter")).toBeInTheDocument();
  // Teaching order (position), not code order: "2 Bonding" comes first.
  const text = cls
    .getByText("2 Bonding")
    .compareDocumentPosition(cls.getByText("1 States of matter"));
  expect(text & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(cls.getByText("Forces set")).toBeInTheDocument();
  // Only the one with a scheme offers it.
  expect(cls.getAllByRole("button", { name: /^Open mark scheme for / })).toHaveLength(1);
  expect(cls.getAllByRole("button", { name: /^Open questions for / })).toHaveLength(3);

  const files = within(section("Files"));
  const chemLink = files.getByRole("link", { name: "Chem Y10" });
  expect(chemLink).toHaveAttribute("href", "/tutor/groups/1/resources");
  expect(files.getByRole("link", { name: "Phys Y11" })).toHaveAttribute(
    "href",
    "/tutor/groups/2/resources",
  );
  expect(files.getByText("Moles worksheet")).toBeInTheDocument();
});

test("a file opens through the authenticated fetch, never a raw link", async () => {
  const calls = stub();
  const open = vi.fn();
  vi.stubGlobal("open", open);
  URL.createObjectURL = vi.fn(() => "blob:x");
  renderPage();
  await screen.findByText("Moles worksheet");

  const files = within(section("Files"));
  expect(files.queryByRole("link", { name: /^Open / })).toBeNull();
  fireEvent.click(files.getByRole("button", { name: "Open Moles worksheet" }));
  await waitFor(() => expect(open).toHaveBeenCalledWith("blob:x", "_blank"));
  const hit = calls.find((c) => c.path === "/api/v1/resources/10/file");
  expect(hit).toBeDefined();
});

test("a recording is a safe external link and an unsafe URL gets none", async () => {
  stub();
  renderPage();
  await screen.findByText("Lesson 4");
  const recs = within(section("Recordings"));
  const watch = recs.getAllByRole("link", { name: "Watch Lesson 4" });
  expect(watch).toHaveLength(1);
  expect(watch[0]).toHaveAttribute("href", "https://example.com/rec");
  expect(watch[0]).toHaveAttribute("target", "_blank");
  expect(watch[0]).toHaveAttribute("rel", "noreferrer noopener");
  expect(recs.getByText("Sneaky")).toBeInTheDocument();
  // An unsafe URL is said to be unavailable, not silently dropped.
  expect(recs.getByText("Link not available")).toBeInTheDocument();
  expect(document.querySelector('a[href^="javascript:"]')).toBeNull();
});

test("each empty state says so and points to where the material is added", async () => {
  stub({ classifieds: [], files: [], recordings: [] });
  renderPage();
  const cls = within(
    await screen.findByRole("heading", { name: "Classifieds" }).then(() => section("Classifieds")),
  );
  expect(await cls.findByText("No classifieds yet.")).toBeInTheDocument();
  expect(cls.getByText(/set homework from a class/)).toBeInTheDocument();
  expect(cls.getByRole("link", { name: /set homework/ })).toHaveAttribute("href", "/tutor/classes");
  const files = within(section("Files"));
  expect(await files.findByText("No files shared yet.")).toBeInTheDocument();
  expect(files.getByText(/Resources tab/)).toBeInTheDocument();
  const recs = within(section("Recordings"));
  expect(await recs.findByText("No recordings shared yet.")).toBeInTheDocument();
  expect(recs.getByText(/Resources tab/)).toBeInTheDocument();
});

test("one section failing shows its own error and retry; the others still render", async () => {
  stub({ files: "fail" });
  renderPage();
  await screen.findByText("Bonding set");
  await screen.findByText("Lesson 4");
  const files = within(section("Files"));
  expect(await files.findByRole("alert")).toBeInTheDocument();
  expect(files.getByRole("button", { name: /try again/i })).toBeInTheDocument();
  expect(files.queryByText("No files shared yet.")).toBeNull();
  expect(within(section("Classifieds")).queryByRole("alert")).toBeNull();
  expect(within(section("Recordings")).queryByRole("alert")).toBeNull();
});

test("it is a record: no create, edit or delete controls, and syllabuses point to Subject setup", async () => {
  stub();
  renderPage();
  await screen.findByText("Lesson 4");
  expect(screen.queryByRole("button", { name: CONTROLS })).toBeNull();
  expect(screen.queryByRole("textbox")).toBeNull();
  expect(screen.getByRole("link", { name: "Subject setup" })).toHaveAttribute(
    "href",
    "/tutor/subject-setup#syllabus",
  );
  expect(screen.queryByText("Syllabuses")).toBeNull();
});

test("the controls pattern can match: the class Resources panel does render its add control", async () => {
  stub();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <GroupResourcesPanel groupId={1} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  expect(await screen.findByRole("button", { name: CONTROLS })).toBeInTheDocument();
});

test("a chapters request failing lists the classifieds unfiled with a line saying so", async () => {
  stub({ chapters: "fail" });
  renderPage();
  const cls = within(
    await screen
      .findByRole("heading", { level: 2, name: "Classifieds" })
      .then(() => section("Classifieds")),
  );
  expect(await cls.findByText("Bonding set")).toBeInTheDocument();
  expect(cls.getByText("States set")).toBeInTheDocument();
  expect(cls.getByText(/Chapters couldn.t be loaded/)).toBeInTheDocument();
});

test("a subjects request failing shows the section error with a retry, not a nameless list", async () => {
  stub({ subjects: "fail" });
  renderPage();
  await screen.findByText("Lesson 4");
  const cls = within(section("Classifieds"));
  expect(await cls.findByRole("alert")).toBeInTheDocument();
  expect(cls.getByRole("button", { name: /try again/i })).toBeInTheDocument();
  expect(cls.queryByText("Bonding set")).toBeNull();
  expect(screen.queryByRole("heading", { level: 3, name: "Subject" })).toBeNull();
});

test("a classified whose subject is not in the list goes under Other subjects", async () => {
  stub({ classifieds: [classified({ id: 9, title: "Orphan set", subject_id: 99 })] });
  renderPage();
  const cls = within(
    await screen
      .findByRole("heading", { level: 2, name: "Classifieds" })
      .then(() => section("Classifieds")),
  );
  expect(await cls.findByRole("heading", { level: 3, name: "Other subjects" })).toBeInTheDocument();
  expect(cls.getByText("Orphan set")).toBeInTheDocument();
});

test("a failed refetch keeps the list the tutor is reading", async () => {
  stub();
  const client = renderPage();
  await screen.findByText("Moles worksheet");
  stub({ files: "fail" });
  await client.refetchQueries({ queryKey: ["resources", "library", "file"] });
  const files = within(section("Files"));
  expect(files.getByText("Moles worksheet")).toBeInTheDocument();
  expect(files.queryByRole("alert")).toBeNull();
});

test("the cap line shows at exactly 200 rows and not at 199", async () => {
  const many = (n: number) =>
    Array.from({ length: n }, (_, i) => resource({ id: 100 + i, title: `File ${i}` }));
  stub({ files: many(199) });
  const first = renderPage();
  await screen.findByText("File 0");
  expect(screen.queryByText(/most recent/)).toBeNull();
  first.clear();
  cleanup();
  stub({ files: many(200) });
  renderPage();
  await screen.findByText("File 0");
  expect(
    screen.getByText(
      /Showing the 200 most recent\. Older ones are in each class.s Resources tab\./,
    ),
  ).toBeInTheDocument();
});
