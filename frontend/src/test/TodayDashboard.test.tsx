import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import App from "../App";
import { AuthProvider } from "../auth/AuthContext";
import type { TodayOverview, TodayView } from "../api/today";
import { roughMarkingTime } from "../tutor/today/WeekGlance";

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

const EMPTY_OVERVIEW: TodayOverview = {
  week: {
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
  },
  agenda: [],
  classes: [],
  remarks: [],
};

function stubFetch(
  view: TodayView,
  narrative: string | null = null,
  attention?: unknown[] | "fail",
  overview: TodayOverview | "fail" = EMPTY_OVERVIEW,
) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200 });
      if (url.includes("/auth/me")) return json(TUTOR);
      if (url.includes("/narrative")) {
        return json({ text: narrative, generated_at: null, prompt_version: null });
      }
      if (url.includes("/api/v1/today/overview")) {
        if (overview === "fail") return new Response("{}", { status: 500 });
        return json(overview);
      }
      if (url.includes("/api/v1/today")) return json(view);
      if (url.includes("/assignments/attention")) {
        if (attention === "fail") return new Response("{}", { status: 500 });
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
  localStorage.setItem("avora-tokens", JSON.stringify({ access_token: "t", token_type: "bearer" }));
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

test("every class gets its own card, in the strip's order", async () => {
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

  // One card per class: nothing collapsed or hidden.
  const links = await screen.findAllByRole("link", { name: /^Class \d$/ });
  expect(links.map((l) => l.textContent)).toEqual(
    Array.from({ length: 8 }, (_, i) => `Class ${i + 1}`),
  );
  expect(links[0]).toHaveAttribute("href", "/tutor/groups/1/students");
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
  expect(await screen.findByText("Not enough data yet")).toBeInTheDocument();
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

test("the page is dated in the organization's day, the one its lessons were chosen in", async () => {
  // 10:30 UTC on 2 October is already 3 October in Kiritimati (UTC+14) and
  // still 2 October on any device clock — so a browser-dated eyebrow would sit
  // a day off over the organization's list of lessons.
  vi.useFakeTimers({ toFake: ["Date"], now: new Date("2026-10-02T10:30:00Z") });
  try {
    stubFetch({
      classes: [classRow()],
      lessons: [],
      review_count: 0,
      class_count: 1,
      joined_student_count: 11,
      classes_with_evidence: 1,
    });
    const answer = globalThis.fetch;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) =>
        String(input).includes("/me/organization")
          ? new Response(JSON.stringify({ id: 1, name: "Org", timezone: "Pacific/Kiritimati" }), {
              status: 200,
            })
          : answer(input, init),
      ),
    );
    const label = (timeZone?: string) =>
      new Date().toLocaleDateString(undefined, {
        weekday: "long",
        day: "numeric",
        month: "long",
        timeZone,
      });
    expect(label("Pacific/Kiritimati")).not.toBe(label());

    renderDashboard();
    expect(await screen.findByText(label("Pacific/Kiritimati"))).toBeInTheDocument();
    expect(screen.queryByText(label())).not.toBeInTheDocument();
  } finally {
    vi.useRealTimers();
  }
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

test("an unreadable past paper under NEEDS YOU links to the shelf that fixes it", async () => {
  // Owner decision, 2026-10-02: a paper the AI couldn't read is the tutor's
  // to check and fix, and the fix lives on the past-papers shelf.
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
    [
      {
        assignment_id: null,
        past_paper_id: 9,
        assignment_title: "0620_w26_qp_21.pdf",
        reason: "extraction_failed",
        detail: "No questions were found in the past paper",
        submission_id: null,
        student_name: null,
      },
    ],
  );
  renderDashboard();

  const link = await screen.findByRole("link", { name: /0620_w26_qp_21\.pdf/ });
  expect(link).toHaveAttribute("href", "/tutor/past-papers#paper-9");
  expect(link).toHaveTextContent("past paper");
  expect(screen.getByText("Couldn't read the questions")).toBeInTheDocument();
  // Something needs the tutor, so the day is not called clear.
  expect(screen.queryByText("That's everything. Enjoy your day.")).not.toBeInTheDocument();
});

/* ------------------------------------------------------------------------
   Coherence B: week at a glance, today's agenda, class cards, needs-you.
   ------------------------------------------------------------------------ */

const ONE_CLASS: TodayView = {
  classes: [classRow({ status: "on_track", predicted_grade: "8", score: 82 })],
  lessons: [],
  review_count: 0,
  class_count: 1,
  joined_student_count: 11,
  classes_with_evidence: 1,
};

function overviewWith(over: Partial<TodayOverview>): TodayOverview {
  return { ...EMPTY_OVERVIEW, ...over };
}

function card(over: Partial<TodayOverview["classes"][number]> = {}) {
  return {
    group_id: 5,
    plan_state: "on_track",
    plan_chapter_code: "2",
    plan_chapter_title: "Bonding",
    plan_missed: 0,
    readiness_direction: null,
    readiness_compared_count: 0,
    last_lesson: null,
    homework_out: 0,
    homework_missing: 0,
    attention: null,
    ...over,
  };
}

function agendaItem(over: Partial<TodayOverview["agenda"][number]> = {}) {
  return {
    key: "slot-7",
    group_id: 5,
    group_name: "Physics A",
    subject_name: "Physics",
    slot_id: 7,
    lesson_id: null,
    source: "plan",
    start_time: "16:00:00",
    starts_at: new Date(Date.now() + 10 * 60_000).toISOString(),
    ends_at: new Date(Date.now() + 70 * 60_000).toISOString(),
    duration_min: 60,
    chapter_id: 2,
    chapter_code: "2",
    chapter_title: "Bonding",
    topics: [{ id: 13, code: "2.1", title: "Ionic bonding" }],
    local_date: "2026-10-07",
    recorded: false,
    ...over,
  };
}

test("the week strip says what each figure was counted from", async () => {
  stubFetch(
    ONE_CLASS,
    null,
    [],
    overviewWith({
      week: {
        ...EMPTY_OVERVIEW.week,
        lessons_planned: 5,
        lessons_taught: 3,
        marking_waiting: 4,
        attendance_present: 9,
        attendance_absent: 1,
        attendance_not_taken: 2,
        attendance_rate: 0.9,
        readiness_drop_count: 1,
        readiness_compared_count: 6,
      },
    }),
  );
  renderDashboard();

  expect(await screen.findByText("3 of 5 taught")).toBeInTheDocument();
  expect(screen.getByText("4 pieces")).toBeInTheDocument();
  expect(screen.getByText("90% present")).toBeInTheDocument();
  // Not-taken is stated as left out of the rate, not silently dropped.
  expect(screen.getByText("9 of 10 marked · 2 not taken, left out")).toBeInTheDocument();
  expect(screen.getByText("1 student dropped")).toBeInTheDocument();
  expect(screen.getByText("5+ points, of 6 compared")).toBeInTheDocument();
});

test("the week strip with nothing behind a figure says so, never 0 or 0%", async () => {
  stubFetch(ONE_CLASS, null, []);
  renderDashboard();

  expect(await screen.findByText("No lessons this week")).toBeInTheDocument();
  expect(screen.getByText("No attendance taken this week")).toBeInTheDocument();
  expect(screen.getByText("No history to compare yet")).toBeInTheDocument();
  expect(screen.getByText("Nothing waiting")).toBeInTheDocument();
  expect(screen.queryByText(/0%/)).not.toBeInTheDocument();
});

test("the good news is a real count and an estimate that says it is one", async () => {
  stubFetch(
    ONE_CLASS,
    null,
    [],
    overviewWith({
      week: {
        ...EMPTY_OVERVIEW.week,
        auto_marked_questions: 47,
        auto_marked_estimate_minutes: 188,
      },
    }),
  );
  renderDashboard();

  const line = await screen.findByText(/47 questions marked for you this week/);
  expect(line).toHaveTextContent("roughly 3 hours of marking");
  expect(line).toHaveTextContent("An estimate, at 4 minutes a question.");
});

test("with nothing marked for them there is no good-news line, not a zero", async () => {
  stubFetch(ONE_CLASS, null, []);
  renderDashboard();

  await screen.findByText("Nothing waiting");
  expect(screen.queryByText(/marked for you/)).not.toBeInTheDocument();
});

test("the marking estimate always says roughly, in minutes or hours", () => {
  expect(roughMarkingTime(4)).toBe("roughly 5 minutes");
  expect(roughMarkingTime(48)).toBe("roughly 50 minutes");
  expect(roughMarkingTime(60)).toBe("roughly 1 hour");
  expect(roughMarkingTime(92)).toBe("roughly 1.5 hours");
  expect(roughMarkingTime(188)).toBe("roughly 3 hours");
});

test("today's agenda: a lesson about to start shows its plan, Review and Cancel", async () => {
  const calls: string[] = [];
  stubFetch(ONE_CLASS, null, [], overviewWith({ agenda: [agendaItem()], classes: [card()] }));
  const answer = globalThis.fetch;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      calls.push(`${init?.method ?? "GET"} ${new URL(String(input), "http://x").pathname}`);
      return answer(input, init);
    }),
  );
  renderDashboard();

  expect(await screen.findByText("16:00")).toBeInTheDocument();
  expect(screen.getByText(/in 10 min/)).toBeInTheDocument();
  expect(screen.getByText("Plan: Chapter 2 · Bonding — Ionic bonding")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Review the Physics A lesson" })).toHaveAttribute(
    "href",
    "/tutor/groups/5/schedule?slot=7&date=2026-10-07",
  );
  expect(screen.queryByRole("link", { name: /Record/ })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Cancel the Physics A lesson" }));
  await waitFor(() => expect(calls).toContain("POST /api/v1/groups/5/plan/slots/7/cancel"));
});

test("a lesson that has ended and was not recorded offers Record, dated today", async () => {
  stubFetch(
    ONE_CLASS,
    null,
    [],
    overviewWith({
      agenda: [
        agendaItem({
          starts_at: new Date(Date.now() - 120 * 60_000).toISOString(),
          ends_at: new Date(Date.now() - 60 * 60_000).toISOString(),
        }),
      ],
    }),
  );
  renderDashboard();

  const record = await screen.findByRole("link", {
    name: "Record the Physics A lesson, dated today",
  });
  // Today's date AND that slot — not the plan's next (future) slot.
  expect(record).toHaveAttribute("href", "/tutor/groups/5/schedule?slot=7&date=2026-10-07");
  expect(screen.queryByRole("button", { name: /Cancel/ })).not.toBeInTheDocument();
  expect(screen.queryByRole("link", { name: /Review the/ })).not.toBeInTheDocument();
});

test("a recorded lesson says Recorded and offers attendance", async () => {
  stubFetch(
    ONE_CLASS,
    null,
    [],
    overviewWith({
      agenda: [
        agendaItem({
          key: "lesson-3",
          lesson_id: 3,
          recorded: true,
          starts_at: new Date(Date.now() - 120 * 60_000).toISOString(),
          ends_at: new Date(Date.now() - 60 * 60_000).toISOString(),
        }),
      ],
    }),
  );
  renderDashboard();

  expect(await screen.findByText("Recorded")).toBeInTheDocument();
  expect(
    screen.getByRole("link", { name: "Take attendance for the Physics A lesson" }),
  ).toHaveAttribute("href", "/tutor/groups/5/schedule");
  expect(screen.queryByRole("link", { name: /Record the/ })).not.toBeInTheDocument();
});

test("a lesson under way reads as under way, and a day with none says so", async () => {
  stubFetch(
    ONE_CLASS,
    null,
    [],
    overviewWith({
      agenda: [agendaItem({ starts_at: new Date(Date.now() - 5 * 60_000).toISOString() })],
    }),
  );
  renderDashboard();
  expect(await screen.findByText(/under way/)).toBeInTheDocument();
});

test("a day with no lessons says so", async () => {
  stubFetch(ONE_CLASS, null, []);
  renderDashboard();
  expect(await screen.findByText("No lessons scheduled today.")).toBeInTheDocument();
});

test("if the overview fails to load, the rest of the page stays and Retry is offered", async () => {
  stubFetch(ONE_CLASS, null, [], "fail");
  renderDashboard();

  expect(
    await screen.findByText(/Couldn't load this week and today's lessons/),
  ).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  // The classes still render from the home aggregate.
  expect(screen.getByRole("link", { name: "Physics A" })).toBeInTheDocument();
  // And a failure is not presented as an empty day.
  expect(screen.queryByText("No lessons scheduled today.")).not.toBeInTheDocument();
});

test("a class card carries plan position, readiness, attendance, homework and the reason", async () => {
  stubFetch(
    ONE_CLASS,
    null,
    [],
    overviewWith({
      classes: [
        card({
          plan_state: "behind",
          plan_missed: 2,
          readiness_direction: "down",
          readiness_compared_count: 4,
          last_lesson: {
            lesson_id: 3,
            lesson_date: "2026-10-06",
            present: 7,
            absent: 1,
            not_taken: 1,
          },
          homework_out: 2,
          homework_missing: 6,
          attention: {
            kind: "weak_topic",
            message: "Sara, Omar below 50% on 1.3 Ionic bonding",
            topic_id: 4,
            student_ids: [11, 12],
            student_names: ["Sara", "Omar"],
          },
        }),
      ],
    }),
  );
  renderDashboard();

  expect(await screen.findByRole("link", { name: "2 lessons behind →" })).toBeInTheDocument();
  expect(screen.getByText("Readiness down since last week")).toBeInTheDocument();
  expect(screen.getByText("82%")).toBeInTheDocument();
  expect(screen.getByText("Last lesson: 7 of 9 present · 1 not taken")).toBeInTheDocument();
  expect(screen.getByText("2 homework out · 6 hand-ins missing")).toBeInTheDocument();
  // The reason names the students and the topic, and links to the fix.
  expect(screen.getByText(/Sara, Omar below 50% on 1\.3 Ionic bonding/)).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Open topic →" })).toHaveAttribute(
    "href",
    "/tutor/groups/5/analytics",
  );
  // Never a bare "needs a look".
  expect(screen.queryByText(/needs a look/i)).not.toBeInTheDocument();
  // The card itself opens the class.
  expect(screen.getByRole("link", { name: "Physics A" })).toHaveAttribute(
    "href",
    "/tutor/groups/5/students",
  );
});

test("a card with no data says so in words", async () => {
  stubFetch(
    { ...ONE_CLASS, classes: [classRow({ score: null, status: null, predicted_grade: null })] },
    null,
    [],
    overviewWith({
      classes: [card({ plan_state: "none", plan_chapter_code: null, plan_chapter_title: null })],
    }),
  );
  renderDashboard();

  expect(await screen.findByText("Not enough data yet")).toBeInTheDocument();
  expect(screen.getByText("No teaching plan yet")).toBeInTheDocument();
  expect(screen.getByText("No lessons held yet")).toBeInTheDocument();
  expect(screen.getByText("No homework out")).toBeInTheDocument();
  expect(screen.getByText("Nothing flagged")).toBeInTheDocument();
});

test("a last lesson nobody marked says attendance was not taken, not 0 present", async () => {
  stubFetch(
    ONE_CLASS,
    null,
    [],
    overviewWith({
      classes: [
        card({
          last_lesson: {
            lesson_id: 3,
            lesson_date: "2026-10-06",
            present: 0,
            absent: 0,
            not_taken: 9,
          },
        }),
      ],
    }),
  );
  renderDashboard();
  expect(await screen.findByText("Last lesson: attendance not taken")).toBeInTheDocument();
  expect(screen.queryByText(/0 of 9/)).not.toBeInTheDocument();
});

test("a single dropped student links to their own page", async () => {
  stubFetch(
    ONE_CLASS,
    null,
    [],
    overviewWith({
      classes: [
        card({
          attention: {
            kind: "readiness_drop",
            message: "Sara dropped 5+ points in readiness since last week",
            student_ids: [11],
            student_names: ["Sara"],
          },
        }),
      ],
    }),
  );
  renderDashboard();
  expect(await screen.findByRole("link", { name: "Open student →" })).toHaveAttribute(
    "href",
    "/tutor/students/11",
  );
});

test("Needs you says why: a re-mark request quotes the student, other work its reason", async () => {
  stubFetch(
    { ...ONE_CLASS, review_count: 2 },
    null,
    [
      {
        assignment_id: 3,
        assignment_title: "Forces worksheet",
        reason: "needs_review",
        detail: null,
        submission_id: 7,
        student_name: "Aya Hassan",
      },
      {
        assignment_id: 4,
        assignment_title: "Moles",
        reason: "ai_marked",
        detail: null,
        submission_id: 8,
        student_name: "Omar Ali",
      },
    ],
    overviewWith({
      remarks: [
        {
          submission_id: 7,
          assignment_title: "Forces worksheet",
          student_name: "Aya Hassan",
          group_name: "Physics A",
          reason: "I showed my working",
        },
      ],
    }),
  );
  renderDashboard();

  expect(await screen.findByText("Asked for a re-mark: “I showed my working”")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /Forces worksheet/ })).toHaveAttribute(
    "href",
    "/tutor/submissions/7",
  );
  // The remarked submission is listed once, as the request — not again as a
  // generic "some marks need your decision".
  expect(screen.queryByText("Some marks need your decision")).not.toBeInTheDocument();
  expect(screen.getByText("AI-marked — awaiting your review")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /Moles/ })).toHaveAttribute(
    "href",
    "/tutor/submissions/8",
  );
});

test("a failed overview never prints the sign-off", async () => {
  stubFetch({ ...ONE_CLASS }, null, [], "fail");
  renderDashboard();
  await screen.findByText(/Couldn't load this week and today's lessons/);
  expect(screen.queryByText("That's everything. Enjoy your day.")).not.toBeInTheDocument();
});

test("a failed attention list never prints the sign-off and offers its own retry", async () => {
  stubFetch({ ...ONE_CLASS }, null, "fail");
  renderDashboard();
  expect(await screen.findByText(/Couldn't check what needs you/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  expect(screen.queryByText("That's everything. Enjoy your day.")).not.toBeInTheDocument();
});

test("the behind-plan line links to the class schedule whichever item the card shows", async () => {
  stubFetch(
    ONE_CLASS,
    null,
    [],
    overviewWith({
      classes: [
        card({
          plan_state: "behind",
          plan_missed: 2,
          attention: {
            kind: "weak_topic",
            message: "Sara below 50% on 1.3 Ionic bonding",
            topic_id: 4,
            student_ids: [11],
            student_names: ["Sara"],
          },
        }),
      ],
    }),
  );
  renderDashboard();
  expect(await screen.findByRole("link", { name: "2 lessons behind →" })).toHaveAttribute(
    "href",
    "/tutor/groups/5/schedule",
  );
});
