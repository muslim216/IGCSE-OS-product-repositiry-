import { expect, test } from "vitest";
import {
  MOVEMENT_NOISE_BAND,
  RECENTLY_MARKED_DAYS,
  dueVerdict,
  monthlyGains,
  movementSentence,
  recentlyMarked,
  subjectStrip,
} from "../lib/student";
import type { StudentAssignment } from "../api/homework";
import type { SubjectReadiness } from "../api/readiness";

/* The student surfaces' pure derivations. Unit-tested here so the rules live in
   one place rather than being re-derived inside JSX. */

const NOW = Date.parse("2026-06-15T12:00:00Z");

function marked(id: number, daysAgo: number | null, total: number | null = 12): StudentAssignment {
  return {
    id,
    title: `Piece ${id}`,
    instructions: null,
    due_at: null,
    subject_name: "Chemistry",
    group_name: "Chem",
    question_count: 1,
    total_marks: 18,
    submission_status: "marked",
    my_total: total,
    finalized_at: daysAgo === null ? null : new Date(NOW - daysAgo * 86_400_000).toISOString(),
    highest_in_class: false,
  };
}

function subject(over: Partial<SubjectReadiness> = {}): SubjectReadiness {
  return {
    subject_id: 1,
    subject_name: "Chemistry",
    exam_board: "Edexcel",
    grade_scale: "9-1",
    score: 70,
    predicted_grade: "7",
    status: "on_track",
    averaging_score: null,
    averaging_grade: null,
    marked_piece_count: 0,
    direction: "up",
    month_delta: null,
    topics_with_evidence: 0,
    topic_count: 0,
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

test("counts up to ten are words in the verdict", () => {
  expect(dueVerdict(1)).toBe("One thing to do today.");
  expect(dueVerdict(2)).toBe("Two things to do today.");
  expect(dueVerdict(11)).toBe("11 things to do today.");
});

test("nothing due is a sentence, never a zero", () => {
  expect(dueVerdict(0)).toBe("You're clear. Nothing due.");
});

test("every verdict ends in a full stop", () => {
  // A verdict without one reads as a label rather than an answer.
  for (const n of [0, 1, 3, 12]) expect(dueVerdict(n)).toMatch(/\.$/);
});

test("the subject strip keeps a stable order between visits", () => {
  // A strip that reorders itself as scores move makes the reader hunt for their
  // own subjects, and turns every visit into a ranking.
  const strip = subjectStrip([
    subject({ subject_id: 2, subject_name: "Physics", score: 90 }),
    subject({ subject_id: 1, subject_name: "Biology", score: 20 }),
  ]);
  expect(strip.map((s) => s.subject_name)).toEqual(["Biology", "Physics"]);
});

test("a subject with no evidence keeps a null score rather than a zero", () => {
  expect(subjectStrip([subject({ score: null })])[0].score).toBeNull();
});

test("only work marked inside the window counts as news", () => {
  const rows = recentlyMarked(
    [marked(1, 0), marked(2, RECENTLY_MARKED_DAYS + 1), marked(3, 2)],
    NOW,
  );
  expect(rows.map((r) => r.id)).toEqual([1, 3]);
});

test("work with no finalized date is excluded rather than assumed recent", () => {
  expect(recentlyMarked([marked(1, null)], NOW)).toHaveLength(0);
});

test("work with no total is not a marked result", () => {
  expect(recentlyMarked([marked(1, 1, null)], NOW)).toHaveLength(0);
});

test("only improvements are announced", () => {
  // A student's home is not where they are told they are going backwards — the
  // decline is already on the strip above, paired with its arrow.
  const gains = monthlyGains([
    subject({ subject_id: 1, month_delta: 6 }),
    subject({ subject_id: 2, month_delta: -9 }),
    subject({ subject_id: 3, month_delta: null }),
  ]);
  expect(gains.map((s) => s.subject_id)).toEqual([1]);
});

test("movement inside the noise band is not movement", () => {
  expect(monthlyGains([subject({ month_delta: MOVEMENT_NOISE_BAND })])).toHaveLength(0);
  expect(movementSentence(MOVEMENT_NOISE_BAND)).toBe("You're steady this month.");
});

test("no month to compare means no sentence, not a zero", () => {
  expect(movementSentence(null)).toBeNull();
});

test("movement is stated in whole points", () => {
  expect(movementSentence(6.4)).toBe("You're up 6 this month.");
  expect(movementSentence(-6.4)).toBe("You're down 6 this month.");
});
