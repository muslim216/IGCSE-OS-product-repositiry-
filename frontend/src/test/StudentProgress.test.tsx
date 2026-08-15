import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, test, vi } from "vitest";
import ProgressPage from "../student/ProgressPage";
import { GAP_SENTENCE, gradeGap } from "../lib/student";
import type { SubjectReadiness } from "../api/readiness";

/* Progress: predicted beside averaging, and the sentence explaining the gap.
   The gap is the story — a predicted grade alone reads as a promise. */

function subject(over: Partial<SubjectReadiness> = {}): SubjectReadiness {
  return {
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
    topics: [],
    weak_topics: [],
    engine: "v2",
    is_updating: false,
    computed_at: null,
    rationale: null,
    recommended_revision: null,
    ...over,
  };
}

function stubFetch(subjects: SubjectReadiness[]) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200 });
      if (url.includes("/readiness/me")) {
        return json({ student_id: 1, student_name: "Sara", subjects });
      }
      return json([]);
    }),
  );
}

function renderProgress() {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter>
        <ProgressPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

test("predicted with no marked work states averaging as absent, not equal", async () => {
  stubFetch([subject({ averaging_score: null, averaging_grade: null, marked_piece_count: 0 })]);
  renderProgress();

  expect(await screen.findByText("7")).toBeInTheDocument();
  expect(screen.getByText("not enough data yet")).toBeInTheDocument();
  // The prediction must not be echoed as the average: that claims the record
  // agrees with a forecast drawn from nothing.
  expect(screen.getAllByText("7")).toHaveLength(1);
  expect(screen.queryByText(GAP_SENTENCE.equal)).not.toBeInTheDocument();
});

test("where the average came from travels with it", async () => {
  stubFetch([subject({ marked_piece_count: 5 })]);
  const { container } = renderProgress();
  await screen.findByText("Averaging");
  expect(container.textContent).toContain("from 5 marked pieces");
});

test.each([
  [
    "above",
    subject({ score: 72, predicted_grade: "7", averaging_score: 64, averaging_grade: "6" }),
  ],
  [
    "below",
    subject({ score: 58, predicted_grade: "5", averaging_score: 64, averaging_grade: "6" }),
  ],
  [
    "equal",
    subject({ score: 65, predicted_grade: "6", averaging_score: 64, averaging_grade: "6" }),
  ],
] as const)("the explanation matches the direction of the gap: %s", async (gap, s) => {
  stubFetch([s]);
  renderProgress();
  expect(await screen.findByText(GAP_SENTENCE[gap])).toBeInTheDocument();
});

test("two scores inside one grade read as a match, because that is what is shown", () => {
  // The screen shows "6" twice. A sentence claiming the student is tracking
  // above their average would contradict the two identical grades beside it.
  expect(
    gradeGap(
      subject({ score: 68, predicted_grade: "6", averaging_score: 62, averaging_grade: "6" }),
    ),
  ).toBe("equal");
});

test("no averaging grade means no sentence at all", () => {
  expect(gradeGap(subject({ averaging_grade: null, averaging_score: null }))).toBeNull();
});

test("a weak topic with no evidence behind it says so rather than showing a score", async () => {
  stubFetch([
    subject({
      weak_topics: [{ topic_id: 9, topic_code: "3.2", topic_title: "Rates", score: 41 }],
      topics: [],
    }),
  ]);
  renderProgress();
  expect(await screen.findByText("3.2 Rates")).toBeInTheDocument();
  expect(screen.getAllByText("not enough data yet").length).toBeGreaterThan(0);
});

test("coverage travels with the evidence disclosure", async () => {
  stubFetch([
    subject({
      topics_with_evidence: 2,
      topic_count: 4,
      topics: [
        {
          topic_id: 1,
          topic_code: "1.1",
          topic_title: "Moles",
          score: 70,
          confidence: "high",
          evidence_count: 3,
        },
      ],
    }),
  ]);
  renderProgress();
  expect(await screen.findByText(/2 of 4 topics carry evidence/)).toBeInTheDocument();
});
