import { useQuery } from "@tanstack/react-query";
import { studentRedos, type AttemptRedo } from "../api/students";
import { SectionCard } from "../components/ui";
import { ABSENT } from "../lib/labels";

/** What an earlier attempt scored, in words. The marks are over the questions
 *  that had a final mark; when none did there is no number to show, and none is
 *  invented (`PROD-2`, `UX-19`). */
function earlierAttemptLine(redo: AttemptRedo): string {
  if (redo.previous_final_marks === null || redo.previous_max_marks === null) {
    return "Earlier attempt was not fully marked — no longer counts";
  }
  return `Earlier attempt: ${redo.previous_final_marks} of ${redo.previous_max_marks} — no longer counts`;
}

/**
 * The attempts this tutor set aside so the student could hand work in again.
 * Absent when there are none: a student nobody has redone anything for has
 * nothing to explain. A failed load says so rather than vanishing, since a quiet
 * gap here would read as "nothing was ever set aside".
 */
export function EarlierAttempts({ studentId }: Readonly<{ studentId: number }>) {
  const redos = useQuery({
    queryKey: ["student-redos", studentId],
    queryFn: () => studentRedos(studentId),
  });

  if (redos.isError) {
    return (
      <p role="alert" className="text-sm text-risk-600">
        Could not load the attempts you set aside. {ABSENT.loadFailed}
      </p>
    );
  }
  if (!redos.data || redos.data.length === 0) return null;

  return (
    <SectionCard>
      <section aria-labelledby="earlier-attempts">
        <h2 id="earlier-attempts" className="text-lg text-ink-900">
          Attempts set aside
        </h2>
        <p className="mt-1 max-w-prose text-sm text-ink-500">
          Work you let this student hand in again. The earlier marks are kept on record and do not
          count toward readiness.
        </p>
        <ul className="mt-4 divide-y divide-line">
          {redos.data.map((redo) => (
            <li key={redo.id} className="py-3 text-sm">
              <p className="font-medium text-ink-900">{redo.work_title}</p>
              <p className="mt-0.5 text-ink-700">{earlierAttemptLine(redo)}</p>
              <p className="mt-0.5 text-xs text-ink-500">
                {new Date(redo.created_at).toLocaleDateString()} · allowed by {redo.allowed_by_name}
              </p>
            </li>
          ))}
        </ul>
      </section>
    </SectionCard>
  );
}
