import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, test, vi } from "vitest";
import ProgressPage from "../student/ProgressPage";
import { GAP_REASON, GAP_SENTENCE, gradeGap, thinEvidenceNote } from "../lib/student";
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
    homework_assignment_count: null,
    homework_submitted_count: null,
    topics: [],
    weak_topics: [],
    is_updating: false,
    computed_at: null,
    rationale: null,
    recommended_revision: null,
    ...over,
  };
}

function stubFetch(subjects: SubjectReadiness[], criteria: unknown[] = []) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200 });
      if (url.includes("/readiness/me")) {
        return json({ student_id: 1, student_name: "Sara", subjects });
      }
      if (url.includes("/custom-criteria")) return json(criteria);
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
  await screen.findByText("Averaging grade");
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

test("a weak topic shows its score with the evidence count from its topic row", async () => {
  stubFetch([
    subject({
      weak_topics: [
        { topic_id: 9, topic_code: "3.2", topic_title: "Rates", score: 41, tutor_estimate: false },
      ],
      topics: [
        {
          topic_id: 9,
          topic_code: "3.2",
          topic_title: "Rates",
          score: 41,
          confidence: "medium",
          evidence_count: 2,
          tutor_estimate: false,
        },
      ],
    }),
  ]);
  renderProgress();
  const why = (await screen.findByRole("heading", { name: "Why" })).parentElement!;
  // The topic's name leads; its syllabus code is quiet secondary text. The
  // count is of marked questions — the unit the topic row records.
  expect(within(why).getByText("Rates")).toBeInTheDocument();
  expect(within(why).getByText("3.2")).toBeInTheDocument();
  expect(why.textContent).toContain("41% across 2 marked questions");
});

test("a student with no subjects still sees their all-subject tutor criteria", async () => {
  // The parent's view has no early return, so the student must not see less
  // than their parent does.
  stubFetch(
    [],
    [
      {
        criterion_id: 2,
        name: "Confidence",
        description: null,
        subject_id: null,
        score: 70,
        updated_at: "2026-09-20T10:00:00Z",
        updated_by_id: 1,
        source: "tutor",
      },
    ],
  );
  renderProgress();
  expect(await screen.findByText("Confidence")).toBeInTheDocument();
  expect(screen.getByText("No progress to show yet.")).toBeInTheDocument();
});

test("a weak topic resting on the tutor's estimate is labelled under Why", async () => {
  stubFetch([
    subject({
      weak_topics: [
        { topic_id: 9, topic_code: "3.2", topic_title: "Rates", score: 41, tutor_estimate: true },
      ],
      topics: [],
    }),
  ]);
  renderProgress();
  expect(await screen.findByText("Includes tutor's estimate")).toBeInTheDocument();
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
          tutor_estimate: false,
        },
      ],
    }),
  ]);
  renderProgress();
  expect(await screen.findByText(/2 of 4 topics have marked work/)).toBeInTheDocument();
});

test("a topic resting on the tutor's estimate is labelled under Evidence", async () => {
  stubFetch([
    subject({
      // The backend leaves an estimate-only topic out of this count.
      topics_with_evidence: 0,
      topic_count: 1,
      topics: [
        {
          topic_id: 1,
          topic_code: "1.1",
          topic_title: "Moles",
          score: 40,
          confidence: "low",
          evidence_count: 1,
          tutor_estimate: true,
        },
      ],
    }),
  ]);
  const { container } = renderProgress();
  expect(await screen.findByText("Includes tutor's estimate")).toBeInTheDocument();
  // The estimate is the one item behind this score, and it is not work the
  // student did: "40% across 1 piece of work" claimed a marked piece nobody
  // marked (PROD-8).
  expect(screen.getByText("40% · no marked work yet")).toBeInTheDocument();
  expect(container.textContent).not.toMatch(/across 1/);
});

test("an estimate-only weak topic says so under Why, not a count of work", async () => {
  const rates = {
    topic_id: 9,
    topic_code: "3.2",
    topic_title: "Rates",
    score: 41,
    confidence: "low",
    evidence_count: 1,
    tutor_estimate: true,
  };
  stubFetch([
    subject({
      weak_topics: [
        { topic_id: 9, topic_code: "3.2", topic_title: "Rates", score: 41, tutor_estimate: true },
      ],
      topics: [rates],
    }),
  ]);
  const { container } = renderProgress();
  // Once under Why and once in the evidence list, and the same words both times.
  expect(await screen.findAllByText("41% · no marked work yet")).toHaveLength(2);
  expect(container.textContent).not.toMatch(/piece of work/);
});

test("a topic's count of work leaves out the tutor's estimate", async () => {
  // evidence_count is three marked questions plus the estimate.
  stubFetch([
    subject({
      topics: [
        {
          topic_id: 1,
          topic_code: "1.1",
          topic_title: "Moles",
          score: 55,
          confidence: "medium",
          evidence_count: 4,
          tutor_estimate: true,
        },
      ],
    }),
  ]);
  renderProgress();
  expect(await screen.findByText("55% across 3 marked questions")).toBeInTheDocument();
  expect(screen.getByText("Includes tutor's estimate")).toBeInTheDocument();
});

test("a gap between the two grades is explained, not only stated", async () => {
  // The reported confusion: "Predicted 6 · Averaging 8" with nothing saying why
  // a forecast sits two grades under the student's own marks.
  stubFetch([
    subject({ score: 62, predicted_grade: "6", averaging_score: 80, averaging_grade: "8" }),
  ]);
  renderProgress();
  expect(await screen.findByText(GAP_SENTENCE.below)).toBeInTheDocument();
  expect(screen.getByText(GAP_REASON.below)).toBeInTheDocument();
});

test("matching grades need no explanation", async () => {
  stubFetch([
    subject({ score: 65, predicted_grade: "6", averaging_score: 64, averaging_grade: "6" }),
  ]);
  renderProgress();
  await screen.findByText(GAP_SENTENCE.equal);
  expect(screen.queryByText(GAP_REASON.below)).not.toBeInTheDocument();
  expect(screen.queryByText(GAP_REASON.above)).not.toBeInTheDocument();
});

test("an average resting on one marked piece says it is thin", async () => {
  stubFetch([subject({ marked_piece_count: 1 })]);
  renderProgress();
  expect(await screen.findByText(thinEvidenceNote(1)!)).toBeInTheDocument();
});

test("each grade is labelled as what it is", async () => {
  stubFetch([subject()]);
  renderProgress();
  expect(await screen.findByText("Predicted grade")).toBeInTheDocument();
  expect(screen.getByText("Averaging grade")).toBeInTheDocument();
  expect(screen.getByText("72% ready")).toBeInTheDocument();
});
