import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { listSubjects } from "../api/groups";
import { getGradeBoundaries, saveGradeBoundaries, type GradeBand } from "../api/gradeBoundaries";
import { EmptyState, useToast } from "../components/ui";
import { ABSENT } from "../lib/labels";

/**
 * The grade-boundary editor — what "Set them →" points at.
 *
 * **What it writes.** This organization's own boundaries, in the org-scoped
 * table. It cannot write the global subject default, and no endpoint exists
 * that would let it: `Subject` has no organization, so a write there would move
 * every other tenant's predicted grades (SEC-8).
 *
 * **Defaults are offered, not assumed.** A subject nobody has set opens
 * pre-filled with the published split for its scale, labelled as unconfirmed
 * (PROD-8) — a tutor is never made to type ten numbers before anything works,
 * and is never told a number is theirs when it is not.
 */

function sourceNote(source: "organization" | "subject" | "none"): string {
  if (source === "organization") return "Your organisation's boundaries.";
  if (source === "subject") return "The standard boundaries for this syllabus — not yet confirmed.";
  return "Nothing set yet. These are the published standard boundaries — not yet confirmed.";
}

export default function GradeBoundariesPage() {
  const queryClient = useQueryClient();
  const { toast, showToast } = useToast();
  const subjects = useQuery({ queryKey: ["subjects"], queryFn: listSubjects });
  const [subjectId, setSubjectId] = useState<number | null>(null);
  const selected = subjectId ?? subjects.data?.[0]?.id ?? null;

  const boundaries = useQuery({
    queryKey: ["grade-boundaries", selected],
    queryFn: () => getGradeBoundaries(selected!),
    enabled: selected !== null,
  });

  // Local edit state, seeded from the server's answer. The server value stays
  // in TanStack Query (FE-6); this is the draft the tutor is typing, which is a
  // different thing from what is stored and is not server data.
  const [draft, setDraft] = useState<GradeBand[]>([]);
  useEffect(() => {
    if (boundaries.data) setDraft(boundaries.data.boundaries);
  }, [boundaries.data]);

  const save = useMutation({
    mutationFn: () => saveGradeBoundaries(selected!, draft),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["grade-boundaries", selected] });
      // Every predicted grade in the product is mapped at read time, so the
      // change is live everywhere on the next load — nothing to recompute.
      queryClient.invalidateQueries({ queryKey: ["today"] });
      showToast("Grade boundaries saved.");
    },
  });

  // The order is the meaning: predicted grades are read top to bottom and the
  // first grade whose minimum is met wins, so an out-of-order list silently
  // awards the wrong grade to everyone. Caught here as well as server-side so
  // the tutor sees it beside the field rather than as a rejected save.
  const outOfOrder = draft.some((band, i) => i > 0 && Number(band.min) >= Number(draft[i - 1].min));
  // The backend's _unique_grades validator rejects duplicate labels, but without
  // a matching client check the tutor sees only the generic save-failed message.
  // Mirror it so the reason shows inline beside the fields (Qodo).
  const labels = draft.map((b) => b.grade.trim()).filter(Boolean);
  const duplicateLabels = new Set(labels).size !== labels.length;

  if (subjects.isLoading) {
    return (
      <div aria-busy="true">
        <span aria-hidden className="block h-24 w-full animate-pulse rounded bg-surface-muted" />
      </div>
    );
  }
  if (subjects.isError || !subjects.data || subjects.data.length === 0) {
    return (
      <EmptyState
        title="No subjects yet."
        hint="Grade boundaries are set per subject — add a syllabus first."
      />
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="font-display text-xl font-semibold text-ink-900">Grade boundaries</h2>
        <p className="mt-1 max-w-prose text-sm text-ink-500">
          What percentage earns each grade. Predicted grades across Avora are read through these,
          so a change here is live everywhere on the next page load.
        </p>
      </div>

      <select
        aria-label="Subject"
        value={selected ?? ""}
        onChange={(e) => setSubjectId(Number(e.target.value))}
        className="rounded-md border border-line-control bg-surface px-3 py-2 text-sm"
      >
        {subjects.data.map((s) => (
          <option key={s.id} value={s.id}>
            {s.name} ({s.exam_board} {s.code})
          </option>
        ))}
      </select>

      {boundaries.isLoading ? (
        <span aria-hidden className="block h-32 w-full animate-pulse rounded bg-surface-muted" />
      ) : boundaries.isError || !boundaries.data ? (
        <p className="text-sm text-ink-500">{ABSENT.loadFailed}</p>
      ) : (
        <>
          <p className="text-sm text-ink-500">{sourceNote(boundaries.data.source)}</p>

          {draft.length === 0 ? (
            <p className="text-sm text-ink-500">
              There is no published default for the {boundaries.data.grade_scale} scale — add each
              grade and its minimum below.
            </p>
          ) : (
            <ul className="max-w-sm">
              {draft.map((band, i) => (
                <li key={i} className="flex items-center gap-3 border-t border-line py-2">
                  <input
                    aria-label={`Grade ${i + 1}`}
                    value={band.grade}
                    onChange={(e) =>
                      setDraft(draft.map((b, j) => (i === j ? { ...b, grade: e.target.value } : b)))
                    }
                    className="w-16 rounded-md border border-line-control px-2 py-1 text-sm"
                  />
                  <input
                    aria-label={`Minimum percentage for grade ${band.grade}`}
                    type="number"
                    min={0}
                    max={100}
                    value={band.min}
                    onChange={(e) =>
                      setDraft(
                        draft.map((b, j) => (i === j ? { ...b, min: Number(e.target.value) } : b)),
                      )
                    }
                    className="w-24 rounded-md border border-line-control px-2 py-1 text-sm tabular-nums"
                  />
                  <span className="text-sm text-ink-500">% and above</span>
                  <button
                    type="button"
                    onClick={() => setDraft(draft.filter((_, j) => j !== i))}
                    className="ml-auto text-sm text-ink-500 hover:text-risk-600"
                  >
                    Remove
                  </button>
                </li>
              ))}
            </ul>
          )}

          <div className="flex flex-wrap items-center gap-3">
            <button
              type="button"
              onClick={() => setDraft([...draft, { grade: "", min: 0 }])}
              className="text-sm font-medium text-brand-600 hover:text-brand-700"
            >
              Add a grade
            </button>
            <button
              type="button"
              onClick={() => save.mutate()}
              disabled={save.isPending || outOfOrder || duplicateLabels || draft.length < 2}
              className="rounded-md bg-brand-600 px-4 py-2 text-sm font-medium text-canvas hover:bg-brand-700 disabled:opacity-50"
            >
              {save.isPending ? "Saving…" : "Save boundaries"}
            </button>
          </div>

          {outOfOrder && (
            <p className="text-sm text-risk-600">
              List the highest grade first, with each minimum below the one above it.
            </p>
          )}
          {duplicateLabels && (
            <p className="text-sm text-risk-600">Each grade can appear only once.</p>
          )}
          {draft.length < 2 && (
            <p className="text-sm text-ink-500">Add at least two grades before saving.</p>
          )}
          {save.isError && <p className="text-sm text-risk-600">{ABSENT.loadFailed}</p>}
        </>
      )}
      {toast}
    </div>
  );
}
