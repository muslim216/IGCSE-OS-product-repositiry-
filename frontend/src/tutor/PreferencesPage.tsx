import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { listSubjects } from "../api/groups";
import {
  getReadinessWeights,
  removeReadinessOverride,
  updateReadinessWeights,
  type ReadinessWeights,
} from "../api/readiness";
import { ABSENT } from "../lib/labels";

type WeightKey = Extract<keyof ReadinessWeights, `weight_${string}`>;
type EnabledKey = Extract<keyof ReadinessWeights, `enabled_${string}`>;

/** The six factors the Readiness Engine scores, in the order a tutor is
 * most likely to care about them. */
const FACTORS: { weight: WeightKey; enabled: EnabledKey; label: string; hint: string }[] = [
  {
    weight: "weight_topic_mastery",
    enabled: "enabled_topic_mastery",
    label: "Topic mastery",
    hint: "Per-topic marks from classifieds and homework",
  },
  {
    weight: "weight_past_paper_performance",
    enabled: "enabled_past_paper_performance",
    label: "Past paper performance",
    hint: "Full papers under exam conditions",
  },
  {
    weight: "weight_homework_performance",
    enabled: "enabled_homework_performance",
    label: "Homework performance",
    hint: "Overall homework marks",
  },
  {
    weight: "weight_assessment_performance",
    enabled: "enabled_assessment_performance",
    label: "Assessment performance",
    hint: "Mocks and class tests",
  },
  {
    weight: "weight_syllabus_coverage",
    enabled: "enabled_syllabus_coverage",
    label: "Syllabus coverage",
    hint: "How much of the syllabus has been taught and evidenced",
  },
  {
    weight: "weight_mistake_analysis",
    enabled: "enabled_mistake_analysis",
    label: "Mistake analysis",
    hint: "Recurring mistakes and their severity",
  },
];

/** Mirrors the API's own test for whether a save recomputes: any score input
 * changed. The weak threshold is not one — it is applied when read. Unknown
 * previous values (nothing cached) count as a change, the safe claim. */
function rescores(next: ReadinessWeights, prev: ReadinessWeights | undefined): boolean {
  if (!prev) return true;
  return (
    next.half_life_days !== prev.half_life_days ||
    FACTORS.some((f) => next[f.weight] !== prev[f.weight] || next[f.enabled] !== prev[f.enabled])
  );
}

function Slider({
  label,
  value,
  min,
  max,
  step,
  disabled = false,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  disabled?: boolean;
  onChange: (v: number) => void;
}) {
  return (
    <div>
      <div className="flex items-center justify-between text-sm">
        <span className="font-medium text-ink-700">{label}</span>
        <span className="text-ink-500">{value}</span>
      </div>
      <input
        type="range"
        aria-label={label}
        min={min}
        max={max}
        step={step}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(Number(e.target.value))}
        className="mt-1 w-full accent-brand-600 disabled:opacity-50"
      />
    </div>
  );
}

function sourceNote(data: ReadinessWeights): string | null {
  if (data.subject_id === null) {
    return data.source === "default"
      ? "Built-in defaults — nothing saved yet. These apply to every subject without its own settings."
      : "These apply to every subject without its own settings.";
  }
  if (data.source === "subject") return "This subject has its own settings.";
  return data.source === "account"
    ? "Using your account settings. Saving creates settings for this subject only."
    : "Using the built-in defaults. Saving creates settings for this subject only.";
}

export default function PreferencesPage() {
  const queryClient = useQueryClient();
  const subjects = useQuery({ queryKey: ["subjects"], queryFn: listSubjects });
  // null is the account row ("All subjects").
  const [subjectId, setSubjectId] = useState<number | null>(null);
  const prefs = useQuery({
    queryKey: ["readiness-weights", subjectId],
    queryFn: () => getReadinessWeights(subjectId),
  });

  // The draft the tutor is editing, seeded once per scope rather than on every
  // query update — a refetch would otherwise copy the stored values over
  // unsaved edits (the same guard MistakeCategoriesPage carries). `undefined`
  // means "not seeded"; the form is gated on it matching the scope so one
  // render cannot show the previous scope's values under the new selector.
  const [form, setForm] = useState<ReadinessWeights | null>(null);
  const [hydratedFor, setHydratedFor] = useState<number | null | undefined>(undefined);
  // Seeded only from a settled fetch: revisiting a scope whose cache went
  // stale (an account save changes every subject without an override) would
  // otherwise seed the stale copy, then ignore the refetch as "already seeded"
  // — and saving that form writes the old values as an override.
  useEffect(() => {
    if (prefs.data && !prefs.isFetching && hydratedFor !== prefs.data.subject_id) {
      setHydratedFor(prefs.data.subject_id);
      setForm(prefs.data);
    }
  }, [prefs.data, prefs.isFetching, hydratedFor]);
  // "rescoring" | "threshold": a threshold-only save recomputes nothing (the
  // API skips it — weak topics are read against the threshold at display
  // time), so the banner must not claim a recompute is on its way.
  const [saved, setSaved] = useState<"rescoring" | "threshold" | null>(null);

  // Each mutation carries the scope it was sent for: its callbacks settle after
  // the tutor may have switched the selector, and must not act on the new one.
  const save = useMutation({
    mutationFn: ({ scope, payload }: { scope: number | null; payload: ReadinessWeights }) =>
      updateReadinessWeights(scope, payload),
    onSuccess: (data, { scope, payload }) => {
      // Read before the cache is overwritten: what this scope resolved to
      // until now, which is what the API compared the save against.
      const before = queryClient.getQueryData<ReadinessWeights>(["readiness-weights", scope]);
      // Saving the account row changes what every subject without an override
      // shows, so every scope is refetched, not only this one.
      void queryClient.invalidateQueries({ queryKey: ["readiness-weights"] });
      queryClient.setQueryData(["readiness-weights", scope], data);
      setSaved(rescores(payload, before) ? "rescoring" : "threshold");
      setTimeout(() => setSaved(null), 2000);
    },
  });

  const remove = useMutation({
    mutationFn: (id: number) => removeReadinessOverride(id),
    onSuccess: async (_data, id) => {
      // Re-seed from the account values the subject falls back to — only once
      // the refetch has landed. Resetting first re-seeds from the cached
      // override that was just deleted, and the refetch then arrives for a
      // scope already marked seeded.
      await queryClient.invalidateQueries({ queryKey: ["readiness-weights", id] });
      // Only re-seed if the tutor is still looking at that subject.
      setHydratedFor((current) => (current === id ? undefined : current));
    },
  });

  const ready = form !== null && prefs.data !== undefined && hydratedFor === subjectId;
  // Mirrors the API's own refusal: a score from no factors is not a score.
  const noneEnabled = form !== null && FACTORS.every((f) => !form[f.enabled]);
  // A cleared box is NaN, never sent: the API would refuse it, and 0 would
  // silently hide every weak topic.
  const badThreshold =
    form !== null &&
    !(
      Number.isFinite(form.weak_threshold) &&
      form.weak_threshold >= 0 &&
      form.weak_threshold <= 100
    );

  return (
    <div className="max-w-xl space-y-4">
      <div>
        <h2 className="text-xl font-semibold text-ink-900">Preferences</h2>
        <p className="text-sm text-ink-500">
          Control how much each of the six readiness factors counts towards your students' scores,
          for all subjects or one. Saving recalculates everyone you teach.
        </p>
      </div>

      <select
        aria-label="Settings for"
        value={subjectId ?? ""}
        onChange={(e) => {
          // A message about the last scope's save must not read as this one's.
          save.reset();
          remove.reset();
          setSaved(null);
          setSubjectId(e.target.value === "" ? null : Number(e.target.value));
        }}
        className="rounded-md border border-line-control bg-surface px-3 py-2 text-sm"
      >
        <option value="">All subjects</option>
        {subjects.data?.map((s) => (
          <option key={s.id} value={s.id}>
            {s.name} ({s.exam_board} {s.code})
          </option>
        ))}
      </select>

      {prefs.isError ? (
        <p className="text-sm text-ink-500">{ABSENT.loadFailed}</p>
      ) : !ready ? (
        <span aria-hidden className="block h-64 w-full animate-pulse rounded bg-surface-muted" />
      ) : (
        <div className="space-y-5 rounded-lg border border-line bg-surface p-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-sm text-ink-500">{sourceNote(prefs.data)}</p>
            {prefs.data.subject_id !== null && prefs.data.source !== "subject" && (
              <button
                // Saves the draft on screen — the inherited values plus any
                // edit already made — as this subject's own override. Sending
                // `prefs.data` would store the unedited values while the
                // sliders kept showing the edit as if it had saved.
                onClick={() => save.mutate({ scope: subjectId, payload: form })}
                disabled={save.isPending || noneEnabled || badThreshold}
                className="text-sm font-medium text-brand-600 hover:text-brand-700 disabled:opacity-50"
              >
                Customise for this subject
              </button>
            )}
            {prefs.data.subject_id !== null && prefs.data.source === "subject" && (
              <button
                onClick={() => remove.mutate(prefs.data.subject_id!)}
                disabled={remove.isPending}
                className="text-sm font-medium text-risk-600 hover:underline disabled:opacity-50"
              >
                {remove.isPending ? "Removing…" : "Remove override"}
              </button>
            )}
          </div>
          {FACTORS.map((factor) => (
            <div key={factor.weight} className="space-y-1">
              <label className="flex items-center gap-2 text-sm text-ink-700">
                <input
                  type="checkbox"
                  aria-label={`Counts towards readiness: ${factor.label}`}
                  checked={form[factor.enabled]}
                  onChange={(e) => setForm({ ...form, [factor.enabled]: e.target.checked })}
                  className="accent-brand-600"
                />
                Counts towards readiness
              </label>
              <Slider
                label={factor.label}
                value={form[factor.weight]}
                min={0}
                max={3}
                step={0.1}
                disabled={!form[factor.enabled]}
                onChange={(v) => setForm({ ...form, [factor.weight]: v })}
              />
              <p className="text-xs text-ink-500">{factor.hint}</p>
            </div>
          ))}
          <Slider
            label="Recency half-life (days)"
            value={form.half_life_days}
            min={7}
            max={180}
            step={1}
            onChange={(v) => setForm({ ...form, half_life_days: v })}
          />
          <label className="block text-sm">
            <span className="font-medium text-ink-700">Weak topic threshold</span>
            <span className="mt-1 flex items-center gap-1">
              <input
                type="number"
                aria-label="Weak topic threshold"
                min={0}
                max={100}
                step={1}
                value={Number.isNaN(form.weak_threshold) ? "" : form.weak_threshold}
                onChange={(e) => setForm({ ...form, weak_threshold: e.target.valueAsNumber })}
                className="w-20 rounded-md border border-line-control bg-surface px-2 py-1 text-sm"
              />
              <span className="text-ink-500">%</span>
            </span>
            <span className="mt-1 block text-xs text-ink-500">
              Topics at or below this mastery score are shown as weak. Takes effect straight away;
              no scores are recalculated.
            </span>
          </label>
          <p className="text-xs text-ink-500">
            Higher weights count that factor more; a shorter half-life makes recent evidence
            dominate faster. A factor with no evidence is weighed out of the score rather than
            counted as zero. A switched-off factor never counts, but is still worked out and kept,
            so nothing is lost if you switch it back on.
          </p>

          <div className="flex items-center gap-3">
            <button
              onClick={() => save.mutate({ scope: subjectId, payload: form })}
              disabled={save.isPending || noneEnabled || badThreshold}
              className="rounded-md bg-brand-600 px-4 py-2 text-sm font-medium text-canvas hover:bg-brand-700 disabled:opacity-50"
            >
              {save.isPending ? "Saving…" : "Save"}
            </button>
            {saved && (
              <span className="text-sm text-ok-700">
                {saved === "rescoring" ? "Saved — recomputing readiness…" : "Saved."}
              </span>
            )}
            {noneEnabled && (
              <span className="text-sm text-risk-600">Keep at least one factor switched on.</span>
            )}
            {badThreshold && (
              <span className="text-sm text-risk-600">Enter a threshold from 0 to 100.</span>
            )}
          </div>
          {(save.isError || remove.isError) && (
            <p className="text-sm text-risk-600" role="alert">
              That did not save. {(save.error ?? remove.error)?.message || ABSENT.loadFailed}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
