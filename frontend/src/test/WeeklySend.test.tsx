import { render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, test, vi } from "vitest";
import WeeklySendLink from "../components/WeeklySendLink";
import WeeklySendPage from "../components/WeeklySendPage";
import type { WeeklySend } from "../api/weeklySend";
import { weekLabel } from "../lib/weeklySend";

const WEEK = { week_start: "2026-10-04T18:00:00Z", week_end: "2026-10-11T18:00:00Z" };
const WINDOW = { window_start: WEEK.week_start, window_end: WEEK.week_end };
const BASE = { id: 7, recipient_user_id: 1, tutor: null, student: null, parent: null, ...WEEK };

const TUTOR: WeeklySend = {
  ...BASE,
  audience: "tutor",
  paragraphs: [{ about: "Chem Y10", text: "Bonding has clicked for most of the class." }],
  tutor: {
    ...WINDOW,
    review_queue: 3,
    marked: { marked: 12, auto_finalized: 9 },
    classes: [
      {
        group_id: 5,
        group_name: "Chem Y10",
        subject_name: "Chemistry",
        plan: {
          this_week_chapter: { code: "C1", title: "Atoms" },
          next_chapter: { code: "C2", title: "Bonding" },
          next_chapter_homework_set: false,
          lessons_planned_this_week: 3,
          lessons_taught_this_week: 1,
          lessons_behind: 2,
          lessons_ahead: 0,
          weeks_to_exam: 8,
        },
        verdicts: [
          { status: "on_track", learners: 4 },
          { status: "at_risk", learners: 1 },
          { status: "not_enough_data", learners: 2 },
        ],
        readiness_direction: "up",
        readiness_compared_count: 5,
        weak_topics: [{ title: "Moles", learners: 3 }],
        attendance: { lessons_held: 3, present: 10, absent: 2, not_taken: 1, rate: 0.83 },
        homework: { set_count: 2, handed_in_count: 6, missing_count: 1 },
        punctuality: { on_time: 5, late: 1 },
      },
      {
        group_id: 6,
        group_name: "Phys Y11",
        subject_name: "Physics",
        plan: null,
        verdicts: [{ status: "not_enough_data", learners: 3 }],
        readiness_direction: null,
        readiness_compared_count: 0,
        weak_topics: [],
        attendance: null,
        homework: null,
        punctuality: null,
      },
    ],
  },
};

const PARENT: WeeklySend = {
  ...BASE,
  audience: "parent",
  paragraphs: [{ about: "Sara", text: "A steady week." }],
  parent: {
    ...WINDOW,
    dropped_links: 0,
    children: [
      {
        child_name: "Sara",
        classes: [
          {
            group_name: "Chem Y10",
            subject_name: "Chemistry",
            verdict: "needs_attention",
            readiness_score: 55,
            predicted_grade: "5",
            readiness_direction: "up",
            chapter: { code: "C1", title: "Atoms" },
            attendance: { lessons_held: 2, present: 1, absent: 1, not_taken: 0, rate: 0.5 },
            homework: { set_count: 2, handed_in_count: 1, missing_count: 1 },
          },
        ],
      },
    ],
  },
};

const STUDENT: WeeklySend = {
  ...BASE,
  audience: "student",
  paragraphs: [],
  student: {
    ...WINDOW,
    student_name: "Sara",
    marked: { marked: 2, auto_finalized: 1 },
    classes: [
      {
        group_id: 5,
        group_name: "Chem Y10",
        subject_name: "Chemistry",
        verdict: "at_risk",
        readiness_score: null,
        predicted_grade: null,
        readiness_direction: null,
        weak_topics: ["Moles"],
        this_week_chapter: { code: "C1", title: "Atoms" },
        next_chapter: null,
        attendance: null,
        homework: null,
      },
    ],
  },
};

type Stub = WeeklySend | null | number | "pending";

function stub(send: Stub, earlier: unknown[] = []) {
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (send === "pending") return new Promise<Response>(() => {});
      if (/\/weekly-sends$/.test(url)) {
        return Promise.resolve(new Response(JSON.stringify(earlier), { status: 200 }));
      }
      if (typeof send === "number") {
        return Promise.resolve(new Response(JSON.stringify({ detail: "x" }), { status: send }));
      }
      return Promise.resolve(new Response(JSON.stringify(send), { status: 200 }));
    }),
  );
}

function renderAt(path: string) {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/tutor" element={<WeeklySendLink home="/tutor" />} />
          <Route path="/parent" element={<WeeklySendLink home="/parent" />} />
          <Route path="/:shell/weekly/:sendId" element={<WeeklySendPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

test("the week label reads the stored dates as written", () => {
  expect(weekLabel("2026-10-04T18:00:00Z", "2026-10-11T18:00:00Z")).toBe("4–11 Oct");
  expect(weekLabel("2026-09-28T08:00:00Z", "2026-10-05T08:00:00Z")).toBe("28 Sep – 5 Oct");
});

test("a home page links into the latest send, inside its own shell", async () => {
  stub(PARENT);
  renderAt("/parent");
  expect(await screen.findByText(/This week's send is out/)).toHaveTextContent("4–11 Oct");
  expect(screen.getByRole("link", { name: /Read it/ })).toHaveAttribute("href", "/parent/weekly/7");
});

test("before a first send the home page shows nothing at all", async () => {
  stub(null);
  const { container } = renderAt("/tutor");
  await vi.waitFor(() => expect(fetch).toHaveBeenCalled());
  expect(container).toBeEmptyDOMElement();
});

test("a failed lookup does not put an error on the home page", async () => {
  stub(500);
  const { container } = renderAt("/tutor");
  await vi.waitFor(() => expect(fetch).toHaveBeenCalled());
  expect(container).toBeEmptyDOMElement();
});

test("the tutor's send leads each class with its place in the plan", async () => {
  stub(TUTOR);
  renderAt("/tutor/weekly/7");
  const card = (await screen.findByRole("heading", { name: "Chem Y10" })).closest("section")!;
  const labels = within(card)
    .getAllByRole("term")
    .map((t) => t.textContent);
  expect(labels.slice(0, 4)).toEqual([
    "This week in the plan",
    "Lessons taught",
    "Against the plan",
    "Next",
  ]);
  expect(card).toHaveTextContent("C1 Atoms");
  expect(card).toHaveTextContent("1 of 3 planned");
  expect(card).toHaveTextContent("2 lessons behind");
  expect(card).toHaveTextContent("No homework set for it yet");
  expect(card).toHaveTextContent("8 weeks away");
  expect(card).toHaveTextContent("Moles (3)");
  expect(card).toHaveTextContent("5 on time · 1 late");
  // Learners with no measurement are not shown as a status.
  expect(within(card).queryByText(/not enough data/i)).not.toBeInTheDocument();
  expect(screen.getByText("12 pieces · 9 without you")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "3 submissions" })).toHaveAttribute(
    "href",
    "/tutor/review",
  );
  expect(screen.getByText(/Bonding has clicked/)).toBeInTheDocument();
});

test("a class with nothing measured says so in words, never as zeros", async () => {
  stub(TUTOR);
  renderAt("/tutor/weekly/7");
  const card = (await screen.findByRole("heading", { name: "Phys Y11" })).closest("section")!;
  expect(card).toHaveTextContent("No accepted plan for this class");
  expect(card).toHaveTextContent("not enough data yet");
  expect(card).toHaveTextContent("No lessons this week");
  expect(card).toHaveTextContent("None set or due this week");
  expect(card).not.toHaveTextContent("0%");
});

test("the parent's send is the report: readiness, attendance and homework, no topics", async () => {
  stub(PARENT);
  renderAt("/parent/weekly/7");
  expect(await screen.findByRole("heading", { name: "Sara's week" })).toBeInTheDocument();
  const card = screen.getByRole("heading", { name: "Chemistry" }).closest("section")!;
  expect(card).toHaveTextContent("Grade 5");
  expect(card).toHaveTextContent("Needs attention");
  expect(card).toHaveTextContent("55%");
  expect(card).toHaveTextContent("1 present · 1 absent");
  expect(card).toHaveTextContent("2 set · 1 handed in · 1 missing");
  expect(screen.getByText("A steady week.")).toBeInTheDocument();
  expect(screen.queryByText(/weak topics|focus on|mistake/i)).not.toBeInTheDocument();
});

test("the student's send has no warning badge and no fabricated score", async () => {
  stub(STUDENT);
  renderAt("/student/weekly/7");
  const card = (await screen.findByRole("heading", { name: "Chemistry" })).closest("section")!;
  expect(card).toHaveTextContent("Not enough data yet");
  expect(card).toHaveTextContent("Moles");
  expect(card).not.toHaveTextContent("At risk");
  expect(card).not.toHaveTextContent("0%");
  expect(screen.getByText("2 pieces of your work marked this week.")).toBeInTheDocument();
});

test("earlier weeks are listed and open in the same shell", async () => {
  stub(PARENT, [
    { id: 7, audience: "parent", recipient_user_id: 1, recipient_name: "P", ...WEEK },
    {
      id: 3,
      audience: "parent",
      recipient_user_id: 1,
      recipient_name: "P",
      week_start: "2026-09-27T18:00:00Z",
      week_end: "2026-10-04T18:00:00Z",
    },
  ]);
  renderAt("/parent/weekly/7");
  const link = await screen.findByRole("link", { name: "27 Sep – 4 Oct" });
  expect(link).toHaveAttribute("href", "/parent/weekly/3");
});

test("loading, a send that is not the reader's, and a failed load each say so", async () => {
  stub("pending");
  const first = renderAt("/tutor/weekly/7");
  expect(screen.getByRole("status", { name: "Loading the weekly send" })).toBeInTheDocument();
  first.unmount();

  stub(404);
  const second = renderAt("/tutor/weekly/7");
  expect(await screen.findByText("That weekly send isn't here")).toBeInTheDocument();
  second.unmount();

  stub(500);
  renderAt("/tutor/weekly/7");
  expect(await screen.findByText("The weekly send didn't load")).toBeInTheDocument();
});
