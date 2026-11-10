import type { ReadinessSummary } from "../../api/readiness";

const DIRECTION = { up: "going up", flat: "steady", down: "going down" } as const;

/* The short summary above the tabs: one line per subject, and one line naming
   where attention is needed. A subject with no grade yet says nothing about a
   grade, never a made-up one (PROD-2). */
export default function StudentSummary({ readiness }: { readiness: ReadinessSummary }) {
  const subjects = readiness.subjects;
  if (subjects.length === 0) return null;
  const attention = subjects.filter(
    (s) => s.verdict.status === "needs_attention" || s.verdict.status === "at_risk",
  );
  return (
    <div className="mb-4 space-y-1 text-sm text-ink-700">
      <ul>
        {subjects.map((s) => (
          <li key={s.subject_id}>
            {s.subject_name}
            {s.predicted_grade === null ? " · no grade yet" : ` · grade ${s.predicted_grade}`}
            {s.direction !== null && ` · ${DIRECTION[s.direction]}`}
          </li>
        ))}
      </ul>
      {attention.length > 0 && (
        <p className="text-risk-600">
          Needs attention: {attention.map((s) => s.subject_name).join(", ")}
        </p>
      )}
    </div>
  );
}
