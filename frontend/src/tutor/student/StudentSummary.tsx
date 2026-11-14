import type { ReactNode } from "react";
import type { ReadinessSummary } from "../../api/readiness";
import { DirectionMark } from "../../components/ui";
import { NOT_CALCULATED } from "../../components/VerdictLine";
import { measuredBySeverity, wordingFor } from "../../lib/studentVerdict";
import { ABSENT } from "../../lib/labels";

type Subject = ReadinessSummary["subjects"][number];

// The text colours StatusBadge gives each status, so the same status reads the
// same colour wherever it is shown.
const ATTENTION_TONE = {
  at_risk: "text-risk-600",
  needs_attention: "text-warn-700",
} as const;

/* The grade, worded as the subject card words it (SubjectReadinessCard): a
   failed run says so rather than printing a stale grade, an updating one marks
   the value shown, and a score without a grade names the missing boundaries.
   Never a made-up grade (PROD-2). */
function gradeText(s: Subject): ReactNode {
  if (s.calculation_failed) return NOT_CALCULATED;
  if (s.score === null) return "no grade yet";
  const shown = s.predicted_grade === null ? ABSENT.noBoundaries : `grade ${s.predicted_grade}`;
  return s.is_updating ? `${shown} (${ABSENT.updating})` : shown;
}

/* The short summary above the tabs: one line per subject, and one line per
   status naming where attention is needed, most urgent first. */
export default function StudentSummary({ readiness }: Readonly<{ readiness: ReadinessSummary }>) {
  const subjects = readiness.subjects;
  if (subjects.length === 0) return null;
  const attention = measuredBySeverity(subjects);
  const lines = (["at_risk", "needs_attention"] as const)
    .map((status) => {
      const group = attention.filter((s) => s.verdict.status === status);
      return { status, group, label: group[0] && wordingFor("tutor", group[0].verdict).label };
    })
    .filter((l) => l.group.length > 0);
  return (
    <div data-testid="student-summary" className="mb-4 space-y-1 text-sm text-ink-700">
      <ul>
        {subjects.map((s) => (
          <li key={s.subject_id} data-testid={`summary-subject-${s.subject_name}`}>
            {s.subject_name} · {gradeText(s)}
            {s.direction !== null && (
              <>
                {" · "}
                <DirectionMark direction={s.direction} />
              </>
            )}
          </li>
        ))}
      </ul>
      {lines.map((l) => (
        <p key={l.status} data-testid="summary-attention" className={ATTENTION_TONE[l.status]}>
          {l.label}: {l.group.map((s) => s.subject_name).join(", ")}
        </p>
      ))}
    </div>
  );
}
