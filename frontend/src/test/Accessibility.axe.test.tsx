import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Home, Settings } from "lucide-react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import App from "../App";
import { AuthProvider } from "../auth/AuthContext";
import AppShell from "../components/AppShell";
import { PageHeader } from "../components/page";
import { Modal, SectionCard } from "../components/ui";
import ParentDashboard from "../parent/ParentDashboard";
import StudentHomePage from "../student/StudentHomePage";
import { axeViolations } from "./axe";

/* An automatic accessibility check (UX standards, "No automated accessibility
   testing"). Each test renders a shared piece or a role's home and fails with
   the list of axe violations. Colour contrast is switched off in ./axe because
   jsdom has no painted colours. */

const TUTOR = {
  id: 1,
  email: "demo-tutor@example.com",
  username: null,
  role: "tutor",
  name: "Amina Rahman",
};

const CLASS_ROW = {
  group_id: 5,
  name: "Physics A",
  subject_name: "Physics",
  score: 48,
  predicted_grade: "4",
  status: "at_risk",
  boundaries_missing: false,
  member_count: 11,
  students_with_evidence: 9,
  awaiting_review_count: 1,
};

const SUBJECT = {
  subject_id: 1,
  subject_name: "Chemistry",
  exam_board: "Edexcel IGCSE",
  grade_scale: "9-1",
  score: 72,
  predicted_grade: "7",
  status: "on_track",
  averaging_score: 64,
  averaging_grade: "6",
  marked_piece_count: 5,
  direction: "up",
  month_delta: null,
  topics_with_evidence: 2,
  topic_count: 4,
  homework_assignment_count: null,
  homework_submitted_count: null,
  topics: [],
  weak_topics: [],
  is_updating: false,
  calculation_failed: false,
  computed_at: null,
  rationale: null,
  recommended_revision: null,
  verdict: {
    status: "on_track",
    reason_topics: [],
    next_step: "Nothing flagged in this subject.",
  },
};

const WEEK = {
  week_start: "2026-10-05",
  week_end: "2026-10-11",
  lessons_planned: 0,
  lessons_taught: 0,
  marking_waiting: 0,
  auto_marked_questions: 0,
  auto_marked_estimate_minutes: null,
  auto_marked_minutes_per_question: 4,
  attendance_present: 0,
  attendance_absent: 0,
  attendance_not_taken: 0,
  attendance_rate: null,
  readiness_drop_count: 0,
  readiness_compared_count: 0,
  readiness_drop_threshold: 5,
};

function stubFetch() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200 });
      // Matching is by order: /today/overview must stay above /today.
      if (url.includes("/auth/me")) return json(TUTOR);
      if (url.includes("/narrative")) {
        return json({ text: null, generated_at: null, prompt_version: null });
      }
      if (url.includes("/api/v1/onboarding")) {
        return json({
          complete: true,
          in_flow: false,
          account: { key: "account_basics", kind: "defaulted", state: "set_by_you" },
          subjects: [],
          next_step: null,
        });
      }
      if (url.includes("/api/v1/today/overview")) {
        return json({ week: WEEK, agenda: [], classes: [], remarks: [] });
      }
      if (url.includes("/api/v1/today")) {
        return json({
          classes: [CLASS_ROW],
          lessons: [],
          review_count: 1,
          class_count: 1,
          joined_student_count: 11,
          classes_with_evidence: 9,
        });
      }
      if (url.includes("/assignments/attention")) {
        return json([
          {
            assignment_id: 3,
            assignment_title: "Forces worksheet",
            reason: "needs_review",
            detail: null,
            submission_id: 7,
            student_name: "Aya Hassan",
          },
        ]);
      }
      if (url.includes("/readiness/me")) {
        return json({ student_id: 1, student_name: "Sara", subjects: [SUBJECT] });
      }
      if (url.includes("/me/assignments")) {
        return json([
          {
            id: 1,
            title: "Moles, p.2",
            instructions: null,
            due_at: null,
            subject_name: "Chemistry",
            group_name: "Chem Y10",
            question_count: 4,
            total_marks: 18,
            submission_status: "not_submitted",
            is_open: true,
            my_total: null,
            finalized_at: null,
            highest_in_class: false,
          },
        ]);
      }
      if (url.includes("/me/children")) return json([{ id: 2, name: "Sara", role: "student" }]);
      if (url.includes("/readiness/students/")) {
        return json({ student_id: 2, student_name: "Sara", subjects: [SUBJECT] });
      }
      if (url.includes("/attendance")) {
        return json({ lessons: 0, present: 0, absent: 0, not_taken: 0, rate: null, classes: [] });
      }
      return json([]);
    }),
  );
}

/* These pages render without AppShell, which supplies the <main> landmark they
   sit in at runtime, so axe's "region" rule would misfire on them alone. The
   shell tests keep it on. */
const NO_SHELL = ["region"];

function client() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

/** Axe must see the final DOM, so wait until every query has settled. */
async function settled(qc: QueryClient) {
  await waitFor(() => expect(qc.isFetching()).toBe(0));
}

beforeEach(() => {
  stubFetch();
  localStorage.setItem("avora-tokens", JSON.stringify({ access_token: "t", token_type: "bearer" }));
});

afterEach(() => {
  localStorage.clear();
  vi.unstubAllGlobals();
});

test("AppShell with the tutor navigation has no violations", async () => {
  const nav = [
    { to: "/tutor", label: "Overview", icon: Home },
    { to: "/tutor/settings", label: "Settings", icon: Settings },
  ];
  const qc = client();
  const { baseElement } = render(
    <QueryClientProvider client={qc}>
      <AuthProvider>
        <MemoryRouter initialEntries={["/tutor"]}>
          <Routes>
            <Route element={<AppShell title="Tutor" nav={nav} accountPath="/tutor/settings" />}>
              <Route path="/tutor" element={<h1>Overview</h1>} />
            </Route>
          </Routes>
        </MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>,
  );
  await screen.findByRole("heading", { name: "Overview" });
  await settled(qc);
  expect(await axeViolations(baseElement)).toEqual([]);
});

test("the shared Modal, open, has no violations", async () => {
  const { baseElement } = render(
    <Modal open onClose={() => {}} title="Sure?">
      <button type="button">First</button>
    </Modal>,
  );
  screen.getByRole("dialog");
  // The whole body, so the portalled backdrop button is checked too.
  expect(await axeViolations(baseElement)).toEqual([]);
});

test("PageHeader with actions has no violations", async () => {
  const { baseElement } = render(
    <MemoryRouter>
      <PageHeader
        title="Homework"
        description="Set, mark and review."
        back={{ to: "/tutor", label: "Back to overview" }}
        actions={<button type="button">New homework</button>}
      />
    </MemoryRouter>,
  );
  expect(await axeViolations(baseElement)).toEqual([]);
});

test("SectionCard has no violations", async () => {
  const { baseElement } = render(
    <SectionCard>
      <h2>Classes</h2>
      <p>Physics A</p>
    </SectionCard>,
  );
  expect(await axeViolations(baseElement, NO_SHELL)).toEqual([]);
});

test("the tutor home has no violations", async () => {
  const qc = client();
  const { baseElement } = render(
    <QueryClientProvider client={qc}>
      <AuthProvider>
        <MemoryRouter initialEntries={["/tutor"]}>
          <App />
        </MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>,
  );
  await screen.findByText("Physics A");
  await screen.findByText("Forces worksheet");
  await settled(qc);
  expect(await axeViolations(baseElement)).toEqual([]);
});

test("the student home has no violations", async () => {
  const qc = client();
  const { baseElement } = render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <StudentHomePage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  await screen.findByText("72%");
  await screen.findByText("Moles, p.2");
  await settled(qc);
  expect(await axeViolations(baseElement, NO_SHELL)).toEqual([]);
});

test("the parent dashboard has no violations", async () => {
  const qc = client();
  const { baseElement } = render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <ParentDashboard />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  await screen.findByText("What you can do");
  await settled(qc);
  expect(await axeViolations(baseElement, NO_SHELL)).toEqual([]);
});

test("the check can fail: an image with no text alternative is reported", async () => {
  const { baseElement } = render(<img src="x" />);
  expect(await axeViolations(baseElement)).not.toEqual([]);
});
