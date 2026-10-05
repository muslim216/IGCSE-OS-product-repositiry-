import { Link } from "react-router-dom";
import { ABSENT } from "../lib/labels";
import { subjectSetupPath } from "../lib/subjectSetup";
import { StatusBadge, type ReadinessStatus } from "./ui";

/**
 * Readiness, written one way everywhere: "Grade 6 · On track · 64%".
 *
 * The class header, the class Analytics tab, the Readiness page and the
 * student page each used to print a different subset of these three values, so
 * the same learner read differently depending on which screen the tutor was on
 * (coherence C.6).
 *
 * Each part is omitted when it is absent, never filled in (PROD-2): no score
 * and no status reads "Not enough data yet" rather than 0%; no grade is simply
 * not shown, and when the cause is a subject with no grade boundaries the
 * "set them" hint is kept so the tutor can fix it. The status is the band the
 * backend derived from the grade's boundary position (UX-28) — this component
 * never computes one from the score.
 */
export default function ReadinessFigure({
  score = null,
  grade = null,
  status = null,
  boundariesMissing = false,
  subjectId,
  size = "md",
}: {
  score?: number | null;
  grade?: string | null;
  status?: ReadinessStatus | null;
  /** The subject has no grade boundaries, which is why `grade` is absent. */
  boundariesMissing?: boolean;
  /** Which subject the missing boundaries belong to, so the link opens it. */
  subjectId?: number | null;
  size?: "md" | "lg";
}) {
  const hasAnything = score !== null || grade !== null || status !== null;
  const gradeClass =
    size === "lg"
      ? "font-display text-2xl font-semibold text-ink-900"
      : "font-display text-[15px] text-ink-900";

  const parts: { key: string; node: JSX.Element }[] = [];
  if (grade !== null) {
    parts.push({
      key: "grade",
      node: (
        <span className="text-ink-700">
          Grade <span className={gradeClass}>{grade}</span>
        </span>
      ),
    });
  }
  if (status !== null) parts.push({ key: "status", node: <StatusBadge status={status} /> });
  if (score !== null) {
    parts.push({
      key: "score",
      node: (
        <span className="tabular-nums text-ink-700">
          {Math.round(score)}%<span className="sr-only"> readiness</span>
        </span>
      ),
    });
  }

  return (
    <span className="inline-flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
      {parts.map((p, i) => (
        <span key={p.key} className="inline-flex items-center gap-2">
          {i > 0 && (
            <span aria-hidden className="text-ink-500">
              ·
            </span>
          )}
          {p.node}
        </span>
      ))}
      {!hasAnything && <span className="text-ink-500">Not enough data yet</span>}
      {boundariesMissing && grade === null && (
        <span className="text-ink-500">
          {hasAnything && <span aria-hidden>· </span>}
          <span>{ABSENT.noBoundaries}</span>{" "}
          <Link
            to={subjectSetupPath("boundaries", subjectId)}
            className="font-medium text-brand-600 hover:text-brand-700"
          >
            {ABSENT.noBoundariesAction}
          </Link>
        </span>
      )}
    </span>
  );
}
