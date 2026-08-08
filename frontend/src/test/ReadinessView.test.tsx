import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import { SubjectReadinessCard } from "../components/ReadinessView";
import type { SubjectReadiness } from "../api/readiness";

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
  topics_with_evidence: 0,
  topic_count: 0,
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
