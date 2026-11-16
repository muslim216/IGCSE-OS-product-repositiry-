import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import App from "../App";
import { AuthProvider } from "../auth/AuthContext";
import { formatDayMonth } from "../lib/timezones";

/* T-039: the tutor menu is six items; the rest live inside each class or under
   the name menu. Every old address must still land somewhere sensible. */

const SUBJECT = { id: 1, exam_board: "CIE", code: "0625", name: "Physics", grade_scale: "9-1" };
const CLASS = (id: number) => ({
  id,
  name: `Physics ${id}`,
  subject: SUBJECT,
  member_count: 2,
  awaiting_review_count: 0,
  published_assignment_count: 0,
  next_lesson: null,
  members: [],
});

let calls: string[] = [];

const PAPER = (id: number, subjectId: number, extra: object = {}) => ({
  id,
  subject_id: subjectId,
  title: `Paper ${id}`,
  display_title: `Paper ${id}`,
  session_label: null,
  paper_number: null,
  total_marks: 80,
  duration_minutes: null,
  paper_name: `paper${id}.pdf`,
  mark_scheme_name: null,
  extraction_error: null,
  question_count: 4,
  ...extra,
});

function stub(
  role: "tutor" | "student" | "parent",
  classes: number,
  more: {
    papers?: unknown[];
    subjects?: unknown[];
    assignments?: unknown[];
    timezone?: string;
    orgPending?: boolean;
  } = {},
) {
  calls = [];
  const user = { id: 1, email: "d@example.com", username: null, role, name: "Demo User" };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      calls.push(url);
      const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200 });
      if (url.includes("/auth/me")) return json(user);
      if (url.includes("/analytics/groups/")) {
        return json({
          weak_students: [],
          weak_topics: [],
          topic_mean_count: 0,
          agreement: { agreement_rate: null, ai_agreed: 0, total_marked_questions: 0 },
        });
      }
      if (url.includes("/today/classes/")) {
        return json({ learners: [], needs_you: [], weak_topics: [], boundaries_missing: false });
      }
      if (url.includes("/past-papers") && more.papers) return json(more.papers);
      if (url.endsWith("/api/v1/subjects") && more.subjects) return json(more.subjects);
      if (url.endsWith("/api/v1/me/organization") && more.orgPending)
        return new Promise<Response>(() => {});
      if (url.endsWith("/api/v1/me/organization") && more.timezone)
        return json({ id: 1, name: "Org", timezone: more.timezone });
      if (url.includes("/assignments/group/") && more.assignments) return json(more.assignments);
      if (/\/api\/v1\/groups\/\d+$/.test(url)) return json(CLASS(Number(url.split("/").pop())));
      if (url.endsWith("/api/v1/groups")) {
        return json(Array.from({ length: classes }, (_, i) => CLASS(i + 5)));
      }
      return json([]);
    }),
  );
}

function Probe() {
  const l = useLocation();
  return <p data-testid="where">{l.pathname + l.search + l.hash}</p>;
}

function renderApp(entry: string) {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <AuthProvider>
        <MemoryRouter initialEntries={[entry]}>
          <App />
          <Probe />
        </MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>,
  );
}

const where = () => screen.getByTestId("where").textContent;

beforeEach(() => {
  localStorage.setItem("avora-tokens", JSON.stringify({ access_token: "t", token_type: "bearer" }));
});
afterEach(() => {
  localStorage.clear();
  vi.unstubAllGlobals();
});

test("the sidebar has six items in the owner's order", async () => {
  stub("tutor", 1);
  renderApp("/tutor");
  const sidebar = await screen.findByRole("navigation", { name: "Tutor navigation" });
  expect(
    within(sidebar)
      .getAllByRole("link")
      .map((l) => l.textContent),
  ).toEqual(["Today", "Mark", "Classes", "Students", "Mocks", "Library"]);
});

test("the name menu opens, takes the keyboard, and Escape returns focus to its button", async () => {
  stub("tutor", 1);
  renderApp("/tutor");
  const button = (await screen.findAllByRole("button", { name: /Demo User/ }))[0];
  expect(button).toHaveAttribute("aria-haspopup", "menu");
  expect(button).toHaveAttribute("aria-expanded", "false");
  fireEvent.click(button);
  const menu = await screen.findByRole("menu");
  const items = within(menu).getAllByRole("menuitem");
  expect(items.map((i) => i.textContent)).toEqual(["Subject setup", "Settings", "Sign out"]);
  expect(items[0]).toHaveFocus();
  fireEvent.keyDown(menu, { key: "ArrowDown" });
  expect(items[1]).toHaveFocus();
  fireEvent.keyDown(menu, { key: "End" });
  expect(items[2]).toHaveFocus();
  fireEvent.keyDown(document, { key: "Escape" });
  await waitFor(() => expect(screen.queryByRole("menu")).not.toBeInTheDocument());
  expect(button).toHaveFocus();
});

test("the name menu leads to Subject setup", async () => {
  stub("tutor", 1);
  renderApp("/tutor");
  fireEvent.click((await screen.findAllByRole("button", { name: /Demo User/ }))[0]);
  fireEvent.click(await screen.findByRole("menuitem", { name: "Subject setup" }));
  await waitFor(() => expect(where()).toBe("/tutor/subject-setup"));
});

test("a student and a parent keep the plain account link, with no name menu", async () => {
  stub("student", 1);
  const view = renderApp("/student");
  await screen.findAllByRole("link", { name: /Your account/ });
  expect(screen.queryByRole("button", { name: /Demo User/ })).not.toBeInTheDocument();
  view.unmount();
  stub("parent", 1);
  renderApp("/parent");
  await screen.findAllByRole("link", { name: /Your account/ });
  expect(screen.queryByRole("button", { name: /Demo User/ })).not.toBeInTheDocument();
});

test("the phone bar has four tabs and More, which holds only Mocks and Library", async () => {
  stub("tutor", 1);
  renderApp("/tutor");
  const bar = await screen.findByRole("navigation", { name: "Tutor tabs" });
  const tabs = within(bar).getAllByRole("link");
  expect(tabs.map((t) => t.textContent)).toEqual(["Today", "Mark", "Classes", "Students"]);
  const more = within(bar).getByRole("button", { name: /More/ });
  for (const target of [...tabs, more]) expect(target.className).toContain("min-h-[44px]");
  fireEvent.click(more);
  const items = within(await screen.findByRole("group", { name: "More" })).getAllByRole("link");
  expect(items.map((i) => i.textContent)).toEqual(["Mocks", "Library"]);
  for (const item of items) expect(item.className).toContain("min-h-[44px]");
});

const ONE = [
  ["/tutor/homework", "/tutor/groups/5/homework"],
  ["/tutor/past-papers", "/tutor/groups/5/homework#past-papers"],
  ["/tutor/papers", "/tutor/groups/5/homework#past-papers"],
  ["/tutor/readiness", "/tutor/groups/5/analytics#readiness"],
  ["/tutor/reports", "/tutor/groups/5/analytics#reports"],
  ["/tutor/past-papers?subject=7#paper-3", "/tutor/past-papers/all?subject=7#paper-3"],
  ["/tutor/past-papers?subject=7", "/tutor/groups/5/homework?subject=7#past-papers"],
] as const;

test.each(ONE)("with one class, %s lands on %s", async (from, to) => {
  stub("tutor", 1);
  renderApp(from);
  await waitFor(() => expect(where()).toBe(to));
});

test.each([
  "/tutor/homework",
  "/tutor/past-papers",
  "/tutor/papers",
  "/tutor/readiness",
  "/tutor/reports",
])("with several classes, %s lands on the class list", async (from) => {
  stub("tutor", 2);
  renderApp(`${from}?subject=7#x`);
  await waitFor(() => expect(where()).toBe("/tutor/classes?subject=7#x"));
});

test.each([
  ["/tutor/reports/5", "/tutor/groups/5/analytics#reports"],
  ["/tutor/today", "/tutor"],
  ["/tutor/booklets?x=1", "/tutor/past-papers/booklets?x=1"],
  ["/tutor/syllabuses", "/tutor/subject-setup#syllabus"],
  ["/tutor/teaching-guidance", "/tutor/subject-setup#teaching-guidance"],
  ["/tutor/marking-rules", "/tutor/subject-setup#marking-rules"],
  ["/tutor/mistake-categories", "/tutor/subject-setup#mistake-categories"],
  ["/tutor/preferences", "/tutor/subject-setup#preferences"],
  ["/tutor/boundaries?subject=7", "/tutor/subject-setup?subject=7#boundaries"],
  ["/tutor/settings", "/tutor/settings"],
  ["/tutor/subject-setup?subject=7#boundaries", "/tutor/subject-setup?subject=7#boundaries"],
  ["/tutor/groups/5/analytics", "/tutor/groups/5/analytics"],
])("%s lands on %s whatever the class count", async (from, to) => {
  stub("tutor", 2);
  renderApp(from);
  await waitFor(() => expect(where()).toBe(to));
});

test("a student or a parent on a tutor path is turned away, and a tutor on a student path too", async () => {
  stub("student", 1);
  const a = renderApp("/tutor/classes");
  await waitFor(() => expect(where()).toBe("/student"));
  a.unmount();
  stub("parent", 1);
  const b = renderApp("/tutor/homework");
  await waitFor(() => expect(where()).toBe("/parent"));
  b.unmount();
  stub("tutor", 1);
  renderApp("/student/mocks/3");
  await waitFor(() => expect(where()).toBe("/tutor"));
});

test("the student list pages still have the menu", async () => {
  stub("student", 1);
  renderApp("/student/mocks");
  expect(await screen.findByRole("navigation", { name: "Student navigation" })).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "Leave the paper" })).not.toBeInTheDocument();
});

test("the class-list tip shows once, is the only notice, and stays dismissed", async () => {
  stub("tutor", 2);
  const first = renderApp("/tutor/past-papers");
  expect(
    await screen.findByText("Past papers now live inside each class, under Work."),
  ).toBeInTheDocument();
  expect(screen.queryAllByRole("alert")).toHaveLength(0);
  fireEvent.click(screen.getByRole("button", { name: "Dismiss tip" }));
  expect(
    screen.queryByText("Past papers now live inside each class, under Work."),
  ).not.toBeInTheDocument();
  first.unmount();

  stub("tutor", 2);
  renderApp("/tutor/past-papers");
  await screen.findByText("Physics 5");
  expect(
    screen.queryByText("Past papers now live inside each class, under Work."),
  ).not.toBeInTheDocument();
});

test("the class page has six tabs, and lights Classes", async () => {
  stub("tutor", 1);
  renderApp("/tutor/groups/5/students");
  const tabs = await screen.findByRole("navigation", { name: "Class sections" });
  expect(
    within(tabs)
      .getAllByRole("link")
      .map((l) => l.textContent),
  ).toEqual(["Work", "Students", "Syllabus", "Schedule", "Resources", "Progress"]);
  const sidebar = screen.getByRole("navigation", { name: "Tutor navigation" });
  expect(within(sidebar).getByRole("link", { name: "Classes" })).toHaveAttribute(
    "aria-current",
    "true",
  );
});

test("an assignment page lights Classes, and there is no Homework item", async () => {
  stub("tutor", 1);
  renderApp("/tutor/assignments/5");
  const sidebar = await screen.findByRole("navigation", { name: "Tutor navigation" });
  expect(within(sidebar).getByRole("link", { name: "Classes" })).toHaveAttribute(
    "aria-current",
    "true",
  );
  expect(within(sidebar).queryByRole("link", { name: "Homework" })).not.toBeInTheDocument();
});

test.each([
  ["/tutor/submissions/3", "Mark"],
  ["/tutor/students/9", "Students"],
  ["/tutor/assignments/5", "Classes"],
  ["/tutor/past-papers/booklets", "Classes"],
  ["/tutor/mocks/2", "Mocks"],
])("on %s the sidebar lights %s and nothing else", async (path, label) => {
  stub("tutor", 1);
  renderApp(path);
  const sidebar = await screen.findByRole("navigation", { name: "Tutor navigation" });
  await waitFor(() =>
    expect(within(sidebar).getByRole("link", { name: label })).toHaveAttribute("aria-current"),
  );
  expect(sidebar.querySelectorAll("[aria-current]")).toHaveLength(1);
});

test("the Work tab asks for this class's subject only and links to Booklets", async () => {
  stub("tutor", 1);
  renderApp("/tutor/groups/5/homework");
  const section = await waitFor(() => {
    const el = document.getElementById("past-papers");
    expect(el).not.toBeNull();
    return el as HTMLElement;
  });
  expect(within(section).getByRole("link", { name: /Booklets/ })).toHaveAttribute(
    "href",
    "/tutor/past-papers/booklets",
  );
  await waitFor(() =>
    expect(calls.some((c) => c.includes("/past-papers?subject_id=1"))).toBe(true),
  );
  expect(calls.some((c) => c.endsWith("/api/v1/past-papers"))).toBe(false);
});

test("Progress shows one section at a time, with the hash in the URL, and no class picker", async () => {
  stub("tutor", 2);
  renderApp("/tutor/groups/5/analytics#readiness");
  const switcher = await screen.findByRole("navigation", { name: "Progress sections" });
  expect(within(switcher).getByRole("link", { name: "Readiness" })).toHaveAttribute(
    "aria-current",
    "true",
  );
  expect(screen.queryByRole("combobox", { name: "Class" })).not.toBeInTheDocument();
  expect(screen.queryByText("How often you agreed with the AI")).not.toBeInTheDocument();
  fireEvent.click(within(switcher).getByRole("link", { name: "Analytics" }));
  await waitFor(() => expect(where()).toBe("/tutor/groups/5/analytics"));
  expect(await screen.findByText("How often you agreed with the AI")).toBeInTheDocument();
  fireEvent.click(within(switcher).getByRole("link", { name: "Reports" }));
  await waitFor(() => expect(where()).toBe("/tutor/groups/5/analytics#reports"));
});

test("Booklets still opens at its new address", async () => {
  stub("tutor", 1);
  renderApp("/tutor/past-papers/booklets");
  expect(await screen.findByRole("heading", { level: 1 })).toBeInTheDocument();
  expect(where()).toBe("/tutor/past-papers/booklets");
});

/* T-039 fix round. */

const CHEMISTRY = { id: 2, exam_board: "CIE", code: "0620", name: "Chemistry", grade_scale: "9-1" };

test("the all-subjects past-papers page shows a paper whose subject has no class, and it can be fixed there", async () => {
  stub("tutor", 2, {
    subjects: [SUBJECT, CHEMISTRY],
    papers: [PAPER(9, 2, { title: null, extraction_error: "No questions were found" })],
  });
  renderApp("/tutor/past-papers/all#paper-9");
  expect(await screen.findByRole("heading", { level: 1, name: "Past papers" })).toBeInTheDocument();
  await waitFor(() => expect(document.activeElement?.id).toBe("paper-9"));
  const row = document.getElementById("paper-9") as HTMLElement;
  expect(within(row).getByRole("button", { name: /Try again/ })).toBeInTheDocument();
  expect(within(row).getByRole("button", { name: /Upload a clearer copy/ })).toBeInTheDocument();
  expect(where()).toBe("/tutor/past-papers/all#paper-9");
  expect(calls.some((c) => c.endsWith("/api/v1/past-papers"))).toBe(true);
  const sidebar = screen.getByRole("navigation", { name: "Tutor navigation" });
  expect(within(sidebar).getByRole("link", { name: "Classes" })).toHaveAttribute(
    "aria-current",
    "true",
  );
});

test("a tutor can choose a subject with no class on the all-subjects upload form", async () => {
  stub("tutor", 2, { subjects: [SUBJECT, CHEMISTRY], papers: [] });
  renderApp("/tutor/past-papers/all");
  const subject = await screen.findByRole("combobox", { name: /Subject/ });
  await waitFor(() => expect(within(subject).getByText(/Chemistry/)).toBeInTheDocument());
});

test.each(["/tutor/past-papers#paper-3", "/tutor/papers#paper-3"])(
  "the old to-do link %s lands on the all-subjects page, with one class or several",
  async (from) => {
    for (const n of [1, 2]) {
      stub("tutor", n);
      const view = renderApp(from);
      await waitFor(() => expect(where()).toBe("/tutor/past-papers/all#paper-3"));
      view.unmount();
    }
  },
);

test("the Work tab links to every past paper, whatever its subject", async () => {
  stub("tutor", 1);
  renderApp("/tutor/groups/5/homework");
  const section = await waitFor(() => {
    const el = document.getElementById("past-papers");
    expect(el).not.toBeNull();
    return el as HTMLElement;
  });
  expect(within(section).getByRole("link", { name: "All past papers" })).toHaveAttribute(
    "href",
    "/tutor/past-papers/all",
  );
});

test("inside a class the papers are not filed under an 'Other subject' heading", async () => {
  stub("tutor", 1, { subjects: [SUBJECT], papers: [PAPER(1, 1)] });
  renderApp("/tutor/groups/5/homework");
  await screen.findByText("Paper 1");
  await waitFor(() => expect(calls.some((c) => c.endsWith("/api/v1/subjects"))).toBe(true));
  await new Promise((r) => setTimeout(r, 50));
  expect(screen.queryByText("Other subject")).not.toBeInTheDocument();
  expect(screen.getByRole("heading", { level: 3, name: "Add a paper" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { level: 3, name: "Your papers" })).toBeInTheDocument();
});

test("the all-subjects page keeps its h2 section headings", async () => {
  stub("tutor", 1, { subjects: [SUBJECT], papers: [PAPER(1, 1)] });
  renderApp("/tutor/past-papers/all");
  expect(await screen.findByRole("heading", { level: 2, name: "Add a paper" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { level: 2, name: "Your papers" })).toBeInTheDocument();
});

test("the Work tab keeps each homework's due date", async () => {
  stub("tutor", 1, {
    assignments: [
      {
        id: 1,
        group_id: 5,
        title: "Forces sheet",
        status: "published",
        due_at: "2026-11-20T12:00:00Z",
        question_count: 3,
        total_marks: 10,
        submission_count: 2,
      },
      {
        id: 2,
        group_id: 5,
        title: "Waves",
        status: "draft",
        due_at: null,
        question_count: 1,
        total_marks: 4,
        submission_count: 0,
      },
    ],
  });
  renderApp("/tutor/groups/5/homework");
  expect(await screen.findByText(/^Due .*\b20\b/)).toBeInTheDocument();
  expect(screen.getByText(/No due date/)).toBeInTheDocument();
});

test("while the organization's time zone loads, a due date waits rather than guessing", async () => {
  stub("tutor", 1, {
    orgPending: true,
    assignments: [
      {
        id: 1,
        group_id: 5,
        title: "Forces sheet",
        status: "published",
        due_at: "2026-11-20T23:30:00Z",
        question_count: 3,
        total_marks: 10,
        submission_count: 2,
      },
    ],
  });
  renderApp("/tutor/groups/5/homework");
  const marks = await screen.findByText(/10 marks/);
  expect(marks.textContent?.trim()).toBe("10 marks");
  expect(screen.queryByText(/^Due /)).not.toBeInTheDocument();
});

test("the student phone bar is unchanged: three tabs and More", async () => {
  stub("student", 1);
  renderApp("/student");
  const bar = await screen.findByRole("navigation", { name: "Student tabs" });
  expect(
    within(bar)
      .getAllByRole("link")
      .map((l) => l.textContent),
  ).toEqual(["Home", "Progress", "Homework"]);
  expect(within(bar).getByRole("button", { name: /More/ })).toBeInTheDocument();
});

test("a student's sit page is not special-cased: the menu is still there", async () => {
  stub("student", 1);
  renderApp("/student/mocks/3");
  expect(await screen.findByRole("navigation", { name: "Student navigation" })).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "Leave the paper" })).not.toBeInTheDocument();
});

test("a class page does not print its header, tabs or section switch", async () => {
  stub("tutor", 1);
  renderApp("/tutor/groups/5/analytics");
  const tabs = await screen.findByRole("navigation", { name: "Class sections" });
  expect(tabs.className).toContain("print:hidden");
  const heading = screen.getByRole("heading", { level: 1, name: "Physics 5" });
  expect(heading.closest(".print\\:hidden")).not.toBeNull();
  const switcher = screen.getByRole("navigation", { name: "Progress sections" });
  expect(switcher.className).toContain("print:hidden");
});

test("the More sheet is a plain disclosure, not a menu", async () => {
  stub("tutor", 1);
  renderApp("/tutor");
  const bar = await screen.findByRole("navigation", { name: "Tutor tabs" });
  const more = within(bar).getByRole("button", { name: /More/ });
  expect(more).not.toHaveAttribute("aria-haspopup");
  expect(more).toHaveAttribute("aria-expanded", "false");
  fireEvent.click(more);
  expect(more).toHaveAttribute("aria-expanded", "true");
  const sheet = await screen.findByRole("group", { name: "More" });
  expect(more.getAttribute("aria-controls")).toBe(sheet.id);
  expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  expect(screen.queryByRole("menuitem")).not.toBeInTheDocument();
  for (const link of within(sheet).getAllByRole("link")) {
    expect(link.className).toContain("-outline-offset-2");
  }
});

test("the account menu and the More sheet close when the page changes", async () => {
  stub("tutor", 1);
  renderApp("/tutor");
  const bar = await screen.findByRole("navigation", { name: "Tutor tabs" });
  fireEvent.click(within(bar).getByRole("button", { name: /More/ }));
  await screen.findByRole("group", { name: "More" });
  fireEvent.click(within(bar).getByRole("link", { name: "Mark" }));
  await waitFor(() =>
    expect(screen.queryByRole("group", { name: "More" })).not.toBeInTheDocument(),
  );

  fireEvent.click((await screen.findAllByRole("button", { name: /Demo User/ }))[0]);
  await screen.findByRole("menu");
  fireEvent.click(within(bar).getByRole("link", { name: "Today" }));
  await waitFor(() => expect(screen.queryByRole("menu")).not.toBeInTheDocument());
});

test("Tab in the account menu puts focus on its button first, and the backdrop returns it there", async () => {
  stub("tutor", 1);
  renderApp("/tutor");
  const button = (await screen.findAllByRole("button", { name: /Demo User/ }))[0];
  fireEvent.click(button);
  const menu = await screen.findByRole("menu");
  fireEvent.keyDown(menu, { key: "Tab" });
  expect(button).toHaveFocus();
  await waitFor(() => expect(screen.queryByRole("menu")).not.toBeInTheDocument());

  fireEvent.click(button);
  await screen.findByRole("menu");
  const backdrop = document.querySelector<HTMLElement>("button.fixed.inset-0");
  fireEvent.click(backdrop as HTMLElement);
  expect(button).toHaveFocus();
  await waitFor(() => expect(screen.queryByRole("menu")).not.toBeInTheDocument());
});

test("a page inside a destination is current 'true'; the destination's own page is 'page'", async () => {
  stub("tutor", 1);
  const a = renderApp("/tutor/classes");
  const sidebar = await screen.findByRole("navigation", { name: "Tutor navigation" });
  expect(within(sidebar).getByRole("link", { name: "Classes" })).toHaveAttribute(
    "aria-current",
    "page",
  );
  a.unmount();
  renderApp("/tutor/assignments/5");
  const again = await screen.findByRole("navigation", { name: "Tutor navigation" });
  expect(within(again).getByRole("link", { name: "Classes" })).toHaveAttribute(
    "aria-current",
    "true",
  );
});

test("the sidebar's name button says the role, not 'Account'", async () => {
  stub("tutor", 1);
  renderApp("/tutor");
  const button = (await screen.findAllByRole("button", { name: /Demo User/ }))[0];
  expect(button.textContent).toContain("Tutor");
  expect(button.textContent).not.toContain("Account");
});

test("the moved-page tip names where the page went, has its own memory, and returns focus to the heading", async () => {
  stub("tutor", 2);
  const first = renderApp("/tutor/homework");
  expect(
    await screen.findByText("Homework now lives inside each class, under Work."),
  ).toBeInTheDocument();
  const dismiss = screen.getByRole("button", { name: "Dismiss tip" });
  dismiss.focus();
  fireEvent.click(dismiss);
  expect(screen.queryByText(/Homework now lives/)).not.toBeInTheDocument();
  expect(screen.getByRole("heading", { level: 1 })).toHaveFocus();
  first.unmount();

  // Dismissing one tip does not hide a different one.
  stub("tutor", 2);
  renderApp("/tutor/reports");
  expect(
    await screen.findByText("Reports now live inside each class, under Progress."),
  ).toBeInTheDocument();
});

test("Progress keeps the search when switching sections, and announces the one shown", async () => {
  stub("tutor", 1);
  renderApp("/tutor/groups/5/analytics?x=1");
  const switcher = await screen.findByRole("navigation", { name: "Progress sections" });
  fireEvent.click(within(switcher).getByRole("link", { name: "Reports" }));
  await waitFor(() => expect(where()).toBe("/tutor/groups/5/analytics?x=1#reports"));
  const status = screen.getByText("Showing Reports");
  expect(status).toHaveAttribute("role", "status");
  expect(status.className).toContain("sr-only");
});

test("a due date is read in the organization's zone, near midnight", async () => {
  // 23:30 UTC on the 20th is already the 21st in Dubai (UTC+4).
  const due = "2026-11-20T23:30:00Z";
  const inDubai = formatDayMonth(new Date(due), "Asia/Dubai");
  expect(inDubai).not.toEqual(formatDayMonth(new Date(due), "UTC"));
  stub("tutor", 1, {
    timezone: "Asia/Dubai",
    assignments: [
      {
        id: 1,
        group_id: 5,
        title: "Forces sheet",
        status: "published",
        due_at: due,
        question_count: 3,
        total_marks: 10,
        submission_count: 2,
      },
    ],
  });
  renderApp("/tutor/groups/5/homework");
  await waitFor(() => expect(screen.getByText(new RegExp(`^Due ${inDubai}`))).toBeInTheDocument());
});
