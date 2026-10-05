import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { listSubjects } from "../api/groups";
import {
  getGradeBoundaries,
  saveGradeBoundaries,
  type GradeBand,
  type GradeBoundaries,
} from "../api/gradeBoundaries";
import { Plus } from "lucide-react";
import { Button, Field, Input, Select } from "../components/controls";
import { ErrorState, PageHeader, SectionSkeleton } from "../components/page";
import { EmptyState, SectionCard, useToast } from "../components/ui";
import { friendlyError } from "../lib/errors";
import { useSubjectSetup } from "./SubjectSetupContext";

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

function sourceNote(data: GradeBoundaries): string {
  if (data.source === "organization") return "Your organisation's boundaries.";
  // One source since task 2.4: until these are saved there is no predicted
  // grade for this subject anywhere, so say so rather than implying the
  // defaults below are already in force. Only two scales ship a published
  // split, so the unset case has to answer for both — claiming pre-filled
  // standards for a scale that has none contradicts the list right below it.
  if (data.boundaries.length === 0)
    return "Nothing set yet, so this subject has no predicted grades.";
  return "Nothing set yet, so this subject has no predicted grades. These are the published standard boundaries — save them to use them.";
}

export default function GradeBoundariesPage() {
  const queryClient = useQueryClient();
  const { toast, showToast } = useToast();
  const subjects = useQuery({ queryKey: ["subjects"], queryFn: listSubjects });
  // Inside Subject setup the page-level picker owns the subject (see
  // SubjectSetupContext); standing alone the page keeps its own.
  const setup = useSubjectSetup();
  const [subjectId, setSubjectId] = useState<number | null>(null);
  const selected = setup ? setup.subjectId : (subjectId ?? subjects.data?.[0]?.id ?? null);

  const boundaries = useQuery({
    queryKey: ["grade-boundaries", selected],
    queryFn: () => getGradeBoundaries(selected!),
    enabled: selected !== null,
  });

  // Local edit state, seeded from the server's answer. The server value stays
  // in TanStack Query (FE-6); this is the draft the tutor is typing, which is a
  // different thing from what is stored and is not server data.
  const [draft, setDraft] = useState<GradeBand[]>([]);
  // Seeded once per subject, not on every query update — the guard
  // MarkingRulesPage and MistakeCategoriesPage carry, for the same reason: a
  // window regaining focus refetches, and copying the stored boundaries in
  // again would discard what the tutor has typed and not yet saved. State
  // rather than a ref, because the editor is gated on it.
  const [hydratedFor, setHydratedFor] = useState<number | null>(null);
  useEffect(() => {
    if (boundaries.data && hydratedFor !== boundaries.data.subject_id) {
      setHydratedFor(boundaries.data.subject_id);
      setDraft(boundaries.data.boundaries);
    }
  }, [boundaries.data, hydratedFor]);

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

  const header = (
    <PageHeader
      title="Grade boundaries"
      description="The percentage that earns each grade. Every predicted grade in avora is read through these, so a change here shows everywhere the next time a page loads."
      back={{ to: "/tutor/subject-setup", label: "Subject setup" }}
    />
  );

  if (subjects.isLoading) {
    return (
      <div>
        {header}
        <SectionSkeleton rows={4} label="Loading your subjects" />
      </div>
    );
  }
  // A failed load is not "no subjects": that would send a tutor who has them
  // off to add a syllabus they already have (PROD-2, UX-19).
  if (subjects.isError) {
    return (
      <div>
        {header}
        <ErrorState error={subjects.error} onRetry={() => subjects.refetch()} />
      </div>
    );
  }
  if (!subjects.data || subjects.data.length === 0) {
    return (
      <div>
        {header}
        <SectionCard>
          <EmptyState
            title="No subjects yet."
            hint="Grade boundaries are set per subject — add a syllabus first."
          />
        </SectionCard>
      </div>
    );
  }

  return (
    <div className="max-w-3xl">
      {header}

      <div className="space-y-6">
        {!setup && (
          <Field label="Subject" className="max-w-sm">
            <Select value={selected ?? ""} onChange={(e) => setSubjectId(Number(e.target.value))}>
              {subjects.data.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name} ({s.exam_board} {s.code})
                </option>
              ))}
            </Select>
          </Field>
        )}

        {boundaries.isLoading || (boundaries.data && hydratedFor !== selected) ? (
          <SectionCard>
            <SectionSkeleton rows={5} label="Loading grade boundaries" />
          </SectionCard>
        ) : boundaries.isError || !boundaries.data ? (
          <ErrorState error={boundaries.error} onRetry={() => boundaries.refetch()} />
        ) : (
          <SectionCard className="space-y-4">
            {boundaries.data.source === "organization" ? (
              <p className="text-sm text-ink-500">{sourceNote(boundaries.data)}</p>
            ) : (
              // Not yet in force, so it reads as a caution rather than as a
              // footnote (PROD-8).
              <output className="block rounded-lg bg-warn-100 p-3 text-sm text-warn-700">
                {sourceNote(boundaries.data)}
              </output>
            )}

            {draft.length === 0 ? (
              <p className="text-sm text-ink-500">
                There is no published default for the {boundaries.data.grade_scale} scale — add each
                grade and its minimum below.
              </p>
            ) : (
              <table className="w-full max-w-md text-sm">
                <thead>
                  <tr className="text-left text-xs text-ink-500">
                    <th className="pb-2 pr-3 font-medium">Grade</th>
                    <th className="pb-2 pr-3 font-medium">Minimum</th>
                    <th className="pb-2">
                      <span className="sr-only">Remove</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {draft.map((band, i) => (
                    <tr key={i} className="border-t border-line">
                      <td className="w-24 py-2 pr-3">
                        <Input
                          aria-label={`Grade name, row ${i + 1}`}
                          value={band.grade}
                          onChange={(e) =>
                            setDraft(
                              draft.map((b, j) => (i === j ? { ...b, grade: e.target.value } : b)),
                            )
                          }
                          className="font-medium"
                        />
                      </td>
                      <td className="py-2 pr-3">
                        <span className="flex items-center gap-2">
                          <span className="w-24 shrink-0">
                            <Input
                              aria-label={`Minimum percentage for grade ${band.grade}`}
                              type="number"
                              min={0}
                              max={100}
                              value={band.min}
                              onChange={(e) =>
                                setDraft(
                                  draft.map((b, j) =>
                                    i === j ? { ...b, min: Number(e.target.value) } : b,
                                  ),
                                )
                              }
                              className="tabular-nums"
                            />
                          </span>
                          <span className="whitespace-nowrap text-ink-500">% and above</span>
                        </span>
                      </td>
                      <td className="py-2 text-right">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => setDraft(draft.filter((_, j) => j !== i))}
                        >
                          Remove
                          <span className="sr-only"> grade {band.grade || `in row ${i + 1}`}</span>
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}

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

            <div className="flex flex-wrap items-center gap-3 border-t border-line pt-4">
              <Button variant="ghost" onClick={() => setDraft([...draft, { grade: "", min: 0 }])}>
                <Plus aria-hidden className="h-4 w-4" />
                Add a grade
              </Button>
              <span className="flex-1" />
              <Button
                onClick={() => save.mutate()}
                disabled={outOfOrder || duplicateLabels || draft.length < 2}
                loading={save.isPending}
              >
                Save boundaries
              </Button>
            </div>
            {save.isError && (
              <p role="alert" className="text-sm text-risk-600">
                {friendlyError(save.error, "Your boundaries didn't save. Try again.")}
              </p>
            )}
          </SectionCard>
        )}
      </div>
      {toast}
    </div>
  );
}
