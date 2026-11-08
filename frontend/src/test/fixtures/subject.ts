import type { SubjectReadiness } from "../../api/readiness";

/** An on-track Chemistry subject as the readiness endpoint returns it. */
export function subject(over: Partial<SubjectReadiness> = {}): SubjectReadiness {
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
    calculation_failed: false,
    computed_at: null,
    rationale: null,
    recommended_revision: null,
    verdict: {
      status: "on_track",
      reason_topics: [],
      next_step: "Nothing flagged in this subject.",
    },
    ...over,
  };
}
