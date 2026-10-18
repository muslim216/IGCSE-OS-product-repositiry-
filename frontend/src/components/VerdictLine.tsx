import type { StudentVerdict, VerdictRole } from "../lib/studentVerdict";
import { wordingFor } from "../lib/studentVerdict";
import { ABSENT } from "../lib/labels";
import { StatusBadge, type ReadinessStatus } from "./ui";

/** Said in place of "Not enough data yet" when the last run failed: the shared
    wording, capitalised to start a line, so the two cannot drift. */
export const NOT_CALCULATED =
  ABSENT.notCalculated.charAt(0).toUpperCase() + ABSENT.notCalculated.slice(1);

/** A subject's verdict in the viewer's wording. Adults get the status badge and
    the reason; the student gets plain text, so a kind word is not set in a
    warning colour. The same fields feed all three (coherence C.1).

    `calculationFailed` changes only the no-status wording: a subject whose
    last run failed has no status either, but "not enough data yet" would be
    untrue of it (OPS-10). */
export function VerdictLine({
  role,
  verdict,
  showNextStep = true,
  calculationFailed = false,
}: {
  role: VerdictRole;
  verdict: StudentVerdict;
  showNextStep?: boolean;
  calculationFailed?: boolean;
}) {
  const w = wordingFor(role, verdict);
  const line = verdict.status === "not_enough_data" && calculationFailed ? NOT_CALCULATED : w.line;
  const badged = role !== "student" && verdict.status !== "not_enough_data";
  return (
    <span className="flex flex-wrap items-center gap-x-2.5 gap-y-1 text-sm">
      {badged ? (
        <>
          <StatusBadge status={verdict.status as ReadinessStatus} />
          {w.reason && <span className="text-ink-700">{w.reason}</span>}
        </>
      ) : (
        <span className={role === "student" ? "text-ink-900" : "text-ink-500"}>{line}</span>
      )}
      {showNextStep && verdict.status !== "not_enough_data" && (
        <span className="text-ink-500">{w.nextStep}</span>
      )}
    </span>
  );
}
