import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import { SubjectReadinessCard } from "../components/ReadinessView";
import { NOT_CALCULATED, VerdictLine } from "../components/VerdictLine";
import { ABSENT } from "../lib/labels";
import type { SubjectReadiness } from "../api/readiness";

/* A readiness run whose AI step failed is said as that, never as "not enough
   data yet" — which a student with plenty of marked work would read as untrue
   (OPS-10). With an older score, the score stays and says it is behind. */

const NONE: SubjectReadiness["verdict"] = {
  status: "not_enough_data",
  reason_topics: [],
  next_step: "Marked work will build this picture.",
};

const base: SubjectReadiness = {
  subject_id: 1,
  subject_name: "Chemistry",
  exam_board: "Edexcel IGCSE",
  grade_scale: "9-1",
  score: null,
  predicted_grade: null,
  status: null,
  averaging_score: 64,
  averaging_grade: "6",
  marked_piece_count: 5,
  direction: null,
  month_delta: null,
  topics_with_evidence: 0,
  topic_count: 0,
  homework_assignment_count: null,
  homework_submitted_count: null,
  topics: [],
  weak_topics: [],
  is_updating: false,
  calculation_failed: true,
  computed_at: null,
  rationale: null,
  recommended_revision: null,
  verdict: NONE,
};

test("a subject that couldn't be calculated says so, not 'not enough data yet'", () => {
  const { container } = render(<SubjectReadinessCard subject={base} />);
  // Once in the verdict line, once in place of the score.
  expect(screen.getAllByText(NOT_CALCULATED)).toHaveLength(2);
  expect(container.textContent).not.toMatch(/not enough data yet/i);
  expect(container.textContent).not.toMatch(/\b0%/);
});

test("a subject never calculated still reads 'not enough data yet'", () => {
  render(<SubjectReadinessCard subject={{ ...base, calculation_failed: false }} />);
  expect(screen.queryByText(NOT_CALCULATED)).not.toBeInTheDocument();
  expect(screen.getAllByText("Not enough data yet").length).toBeGreaterThan(0);
});

test("an older score is kept and says it is the last one calculated", () => {
  render(
    <SubjectReadinessCard
      subject={{
        ...base,
        score: 62,
        predicted_grade: "4",
        verdict: { status: "on_track", reason_topics: [], next_step: "Nothing flagged." },
      }}
    />,
  );
  expect(screen.getByText("62%")).toBeInTheDocument();
  expect(screen.getByText(ABSENT.lastCalculated)).toBeInTheDocument();
});

test("while the retry is queued, the updating note speaks instead", () => {
  render(
    <SubjectReadinessCard
      subject={{
        ...base,
        score: 62,
        predicted_grade: "4",
        is_updating: true,
        verdict: { status: "on_track", reason_topics: [], next_step: "Nothing flagged." },
      }}
    />,
  );
  expect(screen.getByText(/while a new one is worked out/)).toBeInTheDocument();
  expect(screen.queryByText(ABSENT.lastCalculated)).not.toBeInTheDocument();
});

test.each(["tutor", "student", "parent"] as const)(
  "the %s's verdict line words a failed run",
  (role) => {
    render(<VerdictLine role={role} verdict={NONE} calculationFailed />);
    expect(screen.getByText(NOT_CALCULATED)).toBeInTheDocument();
  },
);

test("a real status is never replaced by the failed wording", () => {
  render(
    <VerdictLine
      role="tutor"
      verdict={{ status: "at_risk", reason_topics: ["Moles"], next_step: "x" }}
      calculationFailed
    />,
  );
  expect(screen.queryByText(NOT_CALCULATED)).not.toBeInTheDocument();
  expect(screen.getByText("Moles")).toBeInTheDocument();
});

test("with no score and a retry queued, both facts are shown", () => {
  // The last run failed and another is on its way: "Updating…" says the
  // second, and "couldn't be calculated" stays true until it lands.
  render(<SubjectReadinessCard subject={{ ...base, is_updating: true }} />);
  expect(screen.getByText("Updating…")).toBeInTheDocument();
  expect(screen.getAllByText(NOT_CALCULATED).length).toBeGreaterThan(0);
  expect(screen.queryByText(ABSENT.lastCalculated)).not.toBeInTheDocument();
});

test("an older API without the field reads as before", () => {
  const { calculation_failed: _omitted, ...old } = base;
  render(<SubjectReadinessCard subject={old as SubjectReadiness} />);
  expect(screen.queryByText(NOT_CALCULATED)).not.toBeInTheDocument();
  expect(screen.getAllByText("Not enough data yet").length).toBeGreaterThan(0);
});
