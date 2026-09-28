import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  clearCriterionScore,
  getStudentCriteria,
  setCriterionScore,
  type StudentCriterionScore,
} from "../api/customCriteria";
import { ABSENT } from "../lib/labels";
import { EmptyState, SectionCard, SectionHeader } from "./ui";

/**
 * A student's tutor-entered criteria, shown to all three roles (owner decision
 * 18) beside readiness and never in it (decision 6).
 *
 * Every score is the tutor's judgement, not a measurement, so every row says
 * so (`PROD-8`, `UX-20`), and an unscored criterion reads "Not scored" — never
 * 0 and never an empty bar (`PROD-2`, `UX-19`). Only a tutor edits; the server
 * refuses anyone else regardless of `editable` (`SEC-10`).
 */
export default function CustomCriteriaPanel({
  studentId,
  editable = false,
}: {
  studentId: number;
  editable?: boolean;
}) {
  const criteria = useQuery({
    queryKey: ["student-criteria", studentId],
    queryFn: () => getStudentCriteria(studentId),
  });

  if (criteria.isPending) return null;
  // A student or parent with no criteria sees nothing — there is nothing to
  // explain. A tutor sees why the panel is empty and where to fix it.
  if (criteria.data?.length === 0 && !editable) return null;

  return (
    <SectionCard>
      <SectionHeader
        title="Tutor-entered criteria"
        description="Scored by the tutor, not measured by Avora. Not part of the readiness score."
      />
      {criteria.isError ? (
        <p className="mt-3 text-sm text-ink-500">{ABSENT.loadFailed}</p>
      ) : criteria.data.length === 0 ? (
        <EmptyState
          title="No criteria yet"
          hint="Add criteria such as exam technique in Settings, then score them here."
        />
      ) : (
        <ul className="mt-3 divide-y divide-line">
          {criteria.data.map((row) => (
            <CriterionRow
              // Keyed by the stored score too, so the draft re-seeds once a
              // save or clear lands rather than keeping the typed value.
              key={`${row.criterion_id}-${row.score}`}
              studentId={studentId}
              row={row}
              editable={editable}
            />
          ))}
        </ul>
      )}
    </SectionCard>
  );
}

function CriterionRow({
  studentId,
  row,
  editable,
}: {
  studentId: number;
  row: StudentCriterionScore;
  editable: boolean;
}) {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState(row.score === null ? "" : String(row.score));
  const refresh = () =>
    queryClient.invalidateQueries({ queryKey: ["student-criteria", studentId] });
  const save = useMutation({
    mutationFn: (score: number) => setCriterionScore(studentId, row.criterion_id, score),
    onSuccess: refresh,
  });
  const clear = useMutation({
    mutationFn: () => clearCriterionScore(studentId, row.criterion_id),
    onSuccess: refresh,
  });

  const value = Number(draft);
  const valid = draft.trim() !== "" && Number.isInteger(value) && value >= 0 && value <= 100;
  const error = save.error ?? clear.error;
  const busy = save.isPending || clear.isPending;

  return (
    <li className="py-2.5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm font-medium text-ink-900">{row.name}</p>
          {row.description && <p className="text-xs text-ink-500">{row.description}</p>}
        </div>
        <div className="flex items-center gap-2">
          <span className="text-sm text-ink-700">
            {row.score === null ? "Not scored" : `${row.score} / 100`}
          </span>
          <span className="rounded bg-surface-muted px-1.5 py-0.5 text-[11px] font-medium text-ink-500">
            Tutor-entered
          </span>
        </div>
      </div>
      {editable && (
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <input
            type="number"
            min={0}
            max={100}
            step={1}
            aria-label={`Score for ${row.name}`}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            className="w-20 rounded-md border border-line-control bg-canvas px-2 py-1 text-sm text-ink-900"
          />
          <button
            type="button"
            aria-label={`Save score for ${row.name}`}
            disabled={!valid || busy || value === row.score}
            onClick={() => save.mutate(value)}
            className="rounded-md bg-brand-600 px-3 py-1 text-sm font-medium text-canvas hover:bg-brand-700 disabled:opacity-50"
          >
            Save
          </button>
          {row.score !== null && (
            <button
              type="button"
              aria-label={`Clear score for ${row.name}`}
              disabled={busy}
              onClick={() => clear.mutate()}
              className="text-sm font-medium text-ink-500 hover:text-ink-700 disabled:opacity-50"
            >
              Clear
            </button>
          )}
          {error && (
            <p role="alert" className="w-full text-sm text-risk-600">
              {error.message || ABSENT.loadFailed}
            </p>
          )}
        </div>
      )}
    </li>
  );
}
