import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import App from "../App";
import { AuthProvider } from "../auth/AuthContext";
import type { TodayView } from "../api/today";

const TUTOR = {
  id: 1,
  email: "demo-tutor@example.com",
  username: null,
  role: "tutor",
  name: "Amina Rahman",
};

function classRow(over: Partial<TodayView["classes"][number]> = {}) {
  return {
    group_id: 5,
    name: "Physics A",
    subject_name: "Physics",
    score: 48,
    predicted_grade: "4",
    status: "at_risk" as const,
    boundaries_missing: false,
    member_count: 11,
    students_with_evidence: 9,
    awaiting_review_count: 1,
    ...over,
  };
}

const EMPTY_VIEW: TodayView = {
  classes: [],
  lessons: [],
  review_count: 0,
  class_count: 0,
  joined_student_count: 0,
  classes_with_evidence: 0,
};

function stubFetch(view: TodayView, narrative: string | null = null, attention?: unknown[]) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200 });
      if (url.includes("/auth/me")) return json(TUTOR);
      if (url.includes("/narrative")) {
        return json({ text: narrative, generated_at: null, prompt_version: null });
      }
      if (url.includes("/api/v1/today")) return json(view);
      if (url.includes("/assignments/attention")) {
        if (attention !== undefined) return json(attention);
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
      return json([]);
    }),
  );
}

function renderDashboard() {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <AuthProvider>
        <MemoryRouter initialEntries={["/tutor"]}>
          <App />
        </MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  localStorage.setItem(
    "avora-tokens",
    JSON.stringify({ access_token: "t", token_type: "bearer" }),
  );
});

afterEach(() => {
  localStorage.clear();
  vi.unstubAllGlobals();
});

test("a clear day ends with a sentence and renders no empty panels", async () => {
  // Nothing awaiting review means nothing in the attention list either — a
  // fixture with one but not the other is a state the backend cannot produce.
  stubFetch(
    {
      classes: [classRow({ status: "on_track", predicted_grade: "8", score: 82 })],
      lessons: [],
      review_count: 0,
      class_count: 1,
      joined_student_count: 11,
      classes_with_evidence: 1,
    },
    null,
    [],
  );
  renderDashboard();

  expect(await screen.findByText("Your classes are running well.")).toBeInTheDocument();
  expect(await screen.findByText("That's everything. Enjoy your day.")).toBeInTheDocument();
  // NEEDS YOU is not rendered at all when nothing needs them (UX-29).
  expect(screen.queryByText("Needs you")).not.toBeInTheDocument();
  // No fabricated zero anywhere.
  expect(screen.queryByText("0%")).not.toBeInTheDocument();
});

test("eight healthy classes collapse to one line", async () => {
  const classes = Array.from({ length: 8 }, (_, i) =>
    classRow({
      group_id: i + 1,
      name: `Class ${i + 1}`,
      status: "on_track",
      predicted_grade: "8",
      awaiting_review_count: 0,
    }),
  );
  stubFetch({
    classes,
    lessons: [],
    review_count: 0,
    class_count: 8,
    joined_student_count: 80,
    classes_with_evidence: 8,
  });
  renderDashboard();

  // One summarising line, not eight rows — and nothing is hidden: every class
  // name still appears on that line.
  expect(await screen.findByText(/8 classes on track/)).toBeInTheDocument();
  expect(screen.getByText(/Class 1 8/)).toBeInTheDocument();
});

test("the verdict counts classes needing attention, in words", async () => {
  stubFetch({
    classes: [
      classRow({ group_id: 1, name: "A", status: "at_risk" }),
      classRow({ group_id: 2, name: "B", status: "at_risk" }),
      classRow({ group_id: 3, name: "C", status: "on_track" }),
    ],
    lessons: [],
    review_count: 0,
    class_count: 3,
    joined_student_count: 30,
    classes_with_evidence: 3,
  });
  renderDashboard();
  expect(await screen.findByText("Two classes need attention.")).toBeInTheDocument();
});

test("a zero-count clause is omitted rather than rendered as 0", async () => {
  stubFetch({
    classes: [classRow({ status: "on_track", awaiting_review_count: 0 })],
    lessons: [
      {
        id: 1,
        group_id: 5,
        group_name: "Physics A",
        subject_name: "Physics",
        weekday: 2,
        start_time: "16:00:00",
        duration_min: 60,
        title: null,
      },
    ],
    review_count: 0,
    class_count: 1,
    joined_student_count: 11,
    classes_with_evidence: 1,
  });
  renderDashboard();

  // The lessons clause renders; the marking clause is absent, not "0 pieces".
  expect(await screen.findByText("One lesson today")).toBeInTheDocument();
  expect(screen.queryByText(/0 pieces/)).not.toBeInTheDocument();
  expect(screen.queryByText(/zero/i)).not.toBeInTheDocument();
});

test("a class without evidence says so in words, never a zero or an empty bar", async () => {
  stubFetch({
    classes: [
      classRow({ score: null, predicted_grade: null, status: null, students_with_evidence: 0 }),
    ],
    lessons: [],
    review_count: 0,
    class_count: 1,
    joined_student_count: 11,
    classes_with_evidence: 0,
  });
  renderDashboard();

  expect(await screen.findByText("Nothing marked yet.")).toBeInTheDocument();
  expect(await screen.findByText("not enough data yet")).toBeInTheDocument();
  expect(screen.queryByText("0%")).not.toBeInTheDocument();
});

test("a subject with no boundaries offers the action that fixes it", async () => {
  stubFetch({
    classes: [
      classRow({ status: null, predicted_grade: null, boundaries_missing: true, score: 70 }),
    ],
    lessons: [],
    review_count: 0,
    class_count: 1,
    joined_student_count: 11,
    classes_with_evidence: 1,
  });
  renderDashboard();

  expect(await screen.findByText("no grade boundaries set")).toBeInTheDocument();
  expect(screen.getByText("Set them →")).toBeInTheDocument();
});

test("WHAT CHANGED reads the stored narrative, present on open", async () => {
  stubFetch(
    {
      classes: [classRow()],
      lessons: [],
      review_count: 1,
      class_count: 1,
      joined_student_count: 11,
      classes_with_evidence: 1,
    },
    "Bonding is the sticking point this week.",
  );
  renderDashboard();
  expect(await screen.findByText("Bonding is the sticking point this week.")).toBeInTheDocument();
});

test("no narrative yet states the absence rather than rendering an empty panel", async () => {
  stubFetch({
    classes: [classRow()],
    lessons: [],
    review_count: 1,
    class_count: 1,
    joined_student_count: 11,
    classes_with_evidence: 1,
  });
  renderDashboard();
  expect(await screen.findByText("Nothing new since yesterday.")).toBeInTheDocument();
});

test("with no classes the surface offers the one useful action", async () => {
  stubFetch(EMPTY_VIEW);
  renderDashboard();
  expect(await screen.findByText("You haven't set up a class yet.")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /Create a class/ })).toBeInTheDocument();
});

test("no student is named outside the review list", async () => {
  // D3, as narrowed: the home never renders an enumerated list of named learners.
  // The class strip names classes; only NEEDS YOU names work, by its title.
  stubFetch({
    classes: [classRow(), classRow({ group_id: 6, name: "Chem B" })],
    lessons: [],
    review_count: 2,
    class_count: 2,
    joined_student_count: 22,
    classes_with_evidence: 2,
  });
  renderDashboard();

  // Wait for the strip itself (a class name only the aggregate supplies).
  await screen.findByText("Chem B");
  // The class strip carries class names, never a roster of learners.
  expect(screen.queryByText("Aya Hassan")).not.toBeInTheDocument();
});
