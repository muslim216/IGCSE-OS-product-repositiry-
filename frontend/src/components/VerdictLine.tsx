import type { StudentVerdict, VerdictRole } from "../lib/studentVerdict";
import { wordingFor } from "../lib/studentVerdict";
import { StatusBadge, type ReadinessStatus } from "./ui";

/** A subject's verdict in the viewer's wording. Adults get the status badge and
    the reason; the student gets plain text, so a kind word is not set in a
    warning colour. The same fields feed all three (coherence C.1). */
export function VerdictLine({
  role,
  verdict,
  showNextStep = true,
}: {
  role: VerdictRole;
  verdict: StudentVerdict;
  showNextStep?: boolean;
}) {
  const w = wordingFor(role, verdict);
  const badged = role !== "student" && verdict.status !== "not_enough_data";
  return (
    <span className="flex flex-wrap items-center gap-x-2.5 gap-y-1 text-sm">
      {badged ? (
        <>
          <StatusBadge status={verdict.status as ReadinessStatus} />
          {w.reason && <span className="text-ink-700">{w.reason}</span>}
        </>
      ) : (
        <span className={role === "student" ? "text-ink-900" : "text-ink-500"}>{w.line}</span>
      )}
      {showNextStep && verdict.status !== "not_enough_data" && (
        <span className="text-ink-500">{w.nextStep}</span>
      )}
    </span>
  );
}
