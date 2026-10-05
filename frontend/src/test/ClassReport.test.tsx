import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, test, vi } from "vitest";
import ClassReportPage from "../tutor/ClassReportPage";
import ReportsPage from "../tutor/ReportsPage";
import type { ClassReport } from "../api/classReport";

const FULL: ClassReport = {
  group_id: 5,
  name: "Physics A",
  subject_name: "Physics",
  generated_at: "2026-10-07T12:00:00Z",
  readiness: {
    score: 61,
    predicted_grade: "6",
    status: "needs_attention",
    boundaries_missing: false,
    member_count: 3,
    students_with_evidence: 2,
  },
  plan: {
    has_plan: true,
    accepted_at: "2026-09-01T00:00:00Z",
    exam_date: "2026-12-07",
    days_to_exam: 61,
    lessons_planned: 20,
    lessons_taught: 8,
    lessons_left: 12,
    lessons_due: 10,
    behind_by: 2,
    ahead_by: 0,
    position: "behind",
    up_next: {
      scheduled_date: "2026-10-08",
      chapter_code: "C2",
      chapter_title: "Bonding",
      topics: ["Covalent", "Ionic"],
    },
  },
  chapters: [
    {
      chapter_id: 1,
      code: "C1",
      title: "Atoms",
      topics_total: 2,
      topics_taught: 1,
      state: "in_progress",
      lessons_planned: 4,
      lessons_taught: 3,
      topics: [
        {
          topic_id: 11,
          code: "1.1",
          title: "Structure",
          taught: true,
          avg_score: 42,
          student_count: 2,
          weak: true,
          includes_tutor_estimate: false,
        },
        {
          topic_id: 12,
          code: "1.2",
          title: "Isotopes",
          taught: false,
          avg_score: null,
          student_count: null,
          weak: false,
          includes_tutor_estimate: false,
        },
      ],
    },
  ],
  weak_topics: [
    {
      topic_code: "1.1",
      topic_title: "Structure",
      avg_score: 42,
      student_count: 2,
      includes_tutor_estimate: false,
    },
  ],
  weak_threshold: 60,
  mistakes: {
    since: "2026-09-09",
    analysed_questions: 12,
    total_mistakes: 5,
    students_affected: 2,
    categories: [
      {
        category_id: 1,
        category_name: "Units",
        mistakes: 3,
        share: 0.6,
        students_affected: 2,
        severity_total: 5,
      },
    ],
  },
  attendance: {
    present: 3,
    absent: 1,
    not_taken: 1,
    rate: 0.75,
    learners: [
      { student_id: 9, student_name: "Aya Hassan", present: 1, absent: 1, not_taken: 0, rate: 0.5 },
      { student_id: 10, student_name: "Omar Ali", present: 0, absent: 0, not_taken: 1, rate: null },
    ],
  },
};

const NO_DATA: ClassReport = {
  ...FULL,
  readiness: { ...FULL.readiness, score: null, predicted_grade: null, status: null },
  plan: { has_plan: false },
  chapters: [],
  weak_topics: [],
  mistakes: { since: "2026-09-09", analysed_questions: 0, categories: [] },
  attendance: { present: 0, absent: 0, not_taken: 0, rate: null, learners: [] },
};

function stub(body: ClassReport | number | "pending") {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/groups/") && url.includes("/report")) {
        if (body === "pending") return new Promise<Response>(() => {});
        if (typeof body === "number") {
          return new Response(JSON.stringify({ detail: "Group not found" }), { status: body });
        }
        return new Response(JSON.stringify(body), { status: 200 });
      }
      if (url.endsWith("/groups")) {
        return new Response(
          JSON.stringify([
            {
              id: 5,
              name: "Physics A",
              subject: {
                id: 1,
                exam_board: "CIE",
                code: "0625",
                name: "Physics",
                grade_scale: "9-1",
              },
              member_count: 3,
            },
          ]),
          { status: 200 },
        );
      }
      return new Response("[]", { status: 200 });
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
          <Route path="/tutor/reports" element={<ReportsPage />} />
          <Route path="/tutor/reports/:groupId" element={<ClassReportPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

test("lists the tutor's classes, each linking to its report", async () => {
  stub(FULL);
  renderAt("/tutor/reports");
  const link = await screen.findByRole("link", { name: /Physics A/ });
  expect(link).toHaveAttribute("href", "/tutor/reports/5");
});

test("shows a loading state while the report is on its way", () => {
  stub("pending");
  renderAt("/tutor/reports/5");
  expect(screen.getByRole("status", { name: "Loading the report" })).toBeInTheDocument();
});

test("leads with the plan: countdown, position against it, lessons left and what is next", async () => {
  stub(FULL);
  renderAt("/tutor/reports/5");
  const plan = (await screen.findByRole("heading", { name: /Plan & countdown/i })).closest(
    "section",
  )!;
  expect(within(plan).getByText(/61 days/)).toBeInTheDocument();
  expect(within(plan).getByText("Behind by 2 lessons")).toBeInTheDocument();
  expect(within(plan).getByText(/8 of 10 lessons dated before today recorded/)).toBeInTheDocument();
  expect(within(plan).getByText(/12 left in the plan/)).toBeInTheDocument();
  expect(within(plan).getByText(/C2 Bonding/)).toBeInTheDocument();

  // The plan is the first section, ahead of every other.
  const sections = screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent);
  expect(sections.slice(0, 2)).toEqual(["Plan & countdown", "Class readiness"]);
});

test("frames chapters against the plan and flags weak topics at the shared threshold", async () => {
  stub(FULL);
  renderAt("/tutor/reports/5");
  expect(await screen.findByText(/at or below 60%/)).toHaveTextContent("Structure (42%)");
  const row = screen.getByText("1.1 Structure").closest("tr")!;
  expect(row).toHaveTextContent("42%");
  expect(row).toHaveTextContent("Weak");
  // A topic with no measurement says so; it is not a 0%.
  const unmeasured = screen.getByText("1.2 Isotopes").closest("tr")!;
  expect(unmeasured).toHaveTextContent("not enough data yet");
  expect(unmeasured).toHaveTextContent("Not yet");
  expect(screen.getByText(/3 of 4 planned lessons/)).toBeInTheDocument();
});

test("mistake patterns and attendance carry their basis; an unmarked learner has no rate", async () => {
  stub(FULL);
  renderAt("/tutor/reports/5");
  expect(await screen.findByText(/5 mistakes across 12 analysed questions/)).toBeInTheDocument();
  expect(screen.getByText("60%")).toBeInTheDocument();
  expect(screen.getByText(/\(3 of 4 marks\)/)).toBeInTheDocument();
  const omar = screen.getByText("Omar Ali").closest("tr")!;
  expect(omar).toHaveTextContent("not marked yet");
});

test("with no plan and no evidence, every section says what is missing instead of showing zeros", async () => {
  stub(NO_DATA);
  renderAt("/tutor/reports/5");
  expect(await screen.findByText("No teaching plan accepted yet")).toBeInTheDocument();
  expect(screen.getAllByText(/not enough data yet/i).length).toBeGreaterThanOrEqual(2);
  expect(screen.getByText(/no marked work has been analysed/)).toBeInTheDocument();
  expect(screen.getByText("No learners are enrolled yet")).toBeInTheDocument();
  expect(screen.queryByText("0%")).not.toBeInTheDocument();
});

test("a plan with no live lessons says so instead of 0 of 0", async () => {
  stub({
    ...FULL,
    plan: { ...FULL.plan, lessons_planned: 0, lessons_taught: 0, lessons_left: 0, up_next: null },
  });
  renderAt("/tutor/reports/5");
  expect(await screen.findByText("No lessons planned")).toBeInTheDocument();
  expect(screen.queryByText(/0 of 0/)).not.toBeInTheDocument();
});

test("a class that is not the tutor's is a not-found page", async () => {
  stub(404);
  renderAt("/tutor/reports/5");
  expect(await screen.findByText(/couldn't find that class/i)).toBeInTheDocument();
});

test("Print opens the browser's print dialog", async () => {
  stub(FULL);
  const print = vi.fn();
  vi.stubGlobal("print", print);
  renderAt("/tutor/reports/5");
  fireEvent.click(await screen.findByRole("button", { name: /Print/ }));
  expect(print).toHaveBeenCalledOnce();
});
