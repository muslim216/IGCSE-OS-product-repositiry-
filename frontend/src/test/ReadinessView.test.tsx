import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import { SubjectReadinessCard } from "../components/ReadinessView";
import type { SubjectReadiness, TopicReadiness } from "../api/readiness";

const base: SubjectReadiness = {
  subject_id: 1,
  subject_name: "Chemistry",
  exam_board: "Edexcel IGCSE",
  grade_scale: "9-1",
  score: 72,
  predicted_grade: "6",
  status: "needs_attention",
  averaging_score: null,
  averaging_grade: null,
  marked_piece_count: 0,
  direction: null,
  month_delta: null,
  topics_with_evidence: 0,
  topic_count: 0,
  homework_assignment_count: null,
  homework_submitted_count: null,
  topics: [],
  weak_topics: [],
  engine: "v2",
  is_updating: false,
  computed_at: null,
  rationale: null,
  recommended_revision: null,
};

test("shows the score with no updating badge when nothing is queued", () => {
  render(<SubjectReadinessCard subject={base} />);
  expect(screen.getByText("72%")).toBeInTheDocument();
  expect(screen.queryByText("Updating…")).not.toBeInTheDocument();
});

test("says the score is being recalculated rather than passing it off as current", () => {
  render(<SubjectReadinessCard subject={{ ...base, is_updating: true }} />);
  expect(screen.getByText("Updating…")).toBeInTheDocument();
  expect(screen.getByText(/last calculated score/)).toBeInTheDocument();
  // The last known score is still shown — the page doesn't go blank.
  expect(screen.getByText("72%")).toBeInTheDocument();
});

test("surfaces the v2 rationale and revision plan when present", () => {
  render(
    <SubjectReadinessCard
      subject={{
        ...base,
        rationale: "Past paper performance is the weakest factor.",
        recommended_revision: "Two timed questions on bonding.",
      }}
    />,
  );
  expect(screen.getByText(/weakest factor/)).toBeInTheDocument();
  expect(screen.getByText(/timed questions on bonding/)).toBeInTheDocument();
});

test("labels a topic whose score includes the tutor's estimate", () => {
  const topic: TopicReadiness = {
    topic_id: 1,
    topic_code: "1.3",
    topic_title: "Atomic structure",
    score: 40,
    confidence: "low",
    evidence_count: 1,
    tutor_estimate: true,
  };
  render(<SubjectReadinessCard subject={{ ...base, topics: [topic] }} />);
  expect(screen.getByText("includes tutor estimate")).toBeInTheDocument();
});

test("says nothing extra when the score is marked work only", () => {
  const topic: TopicReadiness = {
    topic_id: 1,
    topic_code: "1.3",
    topic_title: "Atomic structure",
    score: 70,
    confidence: "high",
    evidence_count: 3,
    tutor_estimate: false,
  };
  render(<SubjectReadinessCard subject={{ ...base, topics: [topic] }} />);
  expect(screen.queryByText("includes tutor estimate")).not.toBeInTheDocument();
});

test("says so plainly when there is not enough evidence", () => {
  // status travels with the grade: no grade means grade_band() returned null,
  // so a fixture carrying a band here would be a state the backend cannot
  // produce.
  render(
    <SubjectReadinessCard
      subject={{ ...base, score: null, predicted_grade: null, status: null }}
    />,
  );
  expect(screen.getByText("Not enough data yet")).toBeInTheDocument();
});
