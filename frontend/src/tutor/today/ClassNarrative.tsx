import { useQuery } from "@tanstack/react-query";
import { groupNarrative } from "../../api/narrative";
import type { ClassStripRow } from "../../api/today";
import { ABSENT } from "../../lib/labels";

/**
 * WHAT CHANGED — the stored narrative for the class that most wants attention.
 *
 * It is read, not generated: the text was written by a background job and
 * persisted, so this surface renders it on open rather than waiting on a model
 * call (spec §8). While a refresh is in flight the previous text stays on screen
 * marked "Updating…" — the section never blanks, because a blank would read as
 * "nothing happened" when the truth is "we are re-reading" (UX-21).
 *
 * When nothing has been generated yet the section states that in words and is
 * never an empty panel (PROD-2, UX-19).
 */
export default function ClassNarrative({ classes }: { classes: ClassStripRow[] }) {
  // The class the tutor most likely needs context on is the first row, which the
  // backend has already sorted exceptions-first.
  const target = classes[0];

  const narrative = useQuery({
    queryKey: ["narrative", "group", target?.group_id],
    queryFn: () => groupNarrative(target!.group_id),
    enabled: target !== undefined,
  });

  if (!target) return null;

  const text = narrative.data?.text ?? null;
  const refreshing = narrative.isFetching && narrative.data !== undefined;

  return (
    <section>
      <h3 className="avora-label mb-2">What changed</h3>
      {narrative.isLoading ? (
        <span aria-hidden className="block h-10 w-full animate-pulse rounded bg-surface-muted" />
      ) : text ? (
        <p className="max-w-prose text-sm leading-relaxed text-ink-700">
          {text}
          {refreshing && (
            <span className="ml-2 text-xs text-ink-500" aria-live="polite">
              {ABSENT.updating}
            </span>
          )}
        </p>
      ) : narrative.isError ? (
        // A failed fetch is not an absence: claiming "nothing new" when the
        // request failed asserts something the surface does not know (PROD-2).
        <p className="text-sm text-ink-500">{ABSENT.loadFailed}</p>
      ) : (
        <p className="text-sm text-ink-500">Nothing new since yesterday.</p>
      )}
    </section>
  );
}
