import { expect, test } from "vitest";
import { deriveLearnerRows, greetingFor } from "../lib/readiness";
import type { Group } from "../api/groups";
import type { TutorAnalytics } from "../api/readiness";

const subject = { id: 1, exam_board: "CIE", code: "0580", name: "Maths", grade_scale: "9-1" };
const group = (id: number, name: string): Group => ({
  id,
  name,
  subject,
  member_count: 2,
  students_with_evidence: 0,
  published_assignment_count: 0,
  awaiting_review_count: 0,
  next_lesson: null,
});

function analytics(weak_students: TutorAnalytics["weak_students"]): TutorAnalytics {
  return {
    weak_students,
    weak_topics: [],
    agreement: { total_marked_questions: 0, ai_agreed: 0, agreement_rate: null },
  };
}

test("statusOf is no longer exported — bands come from the backend, not a threshold", async () => {
  // A readiness band is now a grade's position in its boundary list (UX-28),
  // computed server-side and delivered as SubjectReadiness.status. No frontend
  // module may re-derive it from a percentage, so statusOf is not a public API.
  const mod = await import("../lib/readiness");
  expect("statusOf" in mod).toBe(false);
});

test("greetingFor tracks the time of day", () => {
  expect(greetingFor(8)).toBe("Good morning");
  expect(greetingFor(13)).toBe("Good afternoon");
  expect(greetingFor(20)).toBe("Good evening");
});

test("rows are sorted lowest-readiness first and tagged with a status", () => {
  const rows = deriveLearnerRows(
    [group(1, "Set A")],
    [
      analytics([
        { student_id: 9, student_name: "Aya", subject_name: "Maths", score: 42.5 },
        { student_id: 10, student_name: "Omar", subject_name: "Maths", score: 81 },
      ]),
    ],
  );
  expect(rows.map((r) => r.student_name)).toEqual(["Aya", "Omar"]);
  expect(rows[0].status).toBe("at_risk");
  expect(rows[1].status).toBe("on_track");
  expect(rows[0].group_name).toBe("Set A");
});

test("a learner in two classes keeps their lowest score for the subject", () => {
  const rows = deriveLearnerRows(
    [group(1, "Set A"), group(2, "Set B")],
    [
      analytics([{ student_id: 9, student_name: "Aya", subject_name: "Maths", score: 78 }]),
      analytics([{ student_id: 9, student_name: "Aya", subject_name: "Maths", score: 51 }]),
    ],
  );
  expect(rows).toHaveLength(1);
  expect(rows[0].score).toBe(51);
  expect(rows[0].status).toBe("needs_attention");
});

test("classes still loading contribute no rows", () => {
  expect(deriveLearnerRows([group(1, "Set A")], [undefined])).toEqual([]);
});
