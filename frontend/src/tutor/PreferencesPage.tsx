import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { listSubjects } from "../api/groups";
import {
  getReadinessWeights,
  removeReadinessOverride,
  updateReadinessWeights,
  type ReadinessWeights,
} from "../api/readiness";
import { Button, Field, Input, Select } from "../components/controls";
import { ErrorState, PageHeader, SectionSkeleton } from "../components/page";
import { SectionCard } from "../components/ui";
import { friendlyError } from "../lib/errors";

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
  display,
  min,
  max,
  step,
  disabled = false,
  onChange,
}: {
  label: string;
  value: number;
  /** The value as read aloud on screen — a bare number never says what it is. */
  display: string;
  min: number;
  max: number;
  step: number;
  disabled?: boolean;
  onChange: (v: number) => void;
}) {
  return (
    <div>
      <div className="flex items-baseline justify-between gap-3 text-sm">
        <span className="font-medium text-ink-900">{label}</span>
        <span className={`tabular-nums ${disabled ? "text-ink-500" : "text-ink-700"}`}>
          {display}
        </span>
      </div>
      <input
        type="range"
        aria-label={label}
        aria-valuetext={display}
        min={min}
        max={max}
        step={step}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(Number(e.target.value))}
        className="mt-2 w-full accent-brand-600 disabled:opacity-50"
      />
    </div>
  );
}

/** A weight as the next save will send it. Not `toFixed(1)`: the slider steps
 * in tenths, but the API stores any value from 0 to 3, so a saved 1.25 read
 * "1.3" on screen and to a screen reader while 1.25 was what got submitted. */
function formatWeight(weight: number): string {
  return Number.isInteger(weight) ? weight.toFixed(1) : String(weight);
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
    <div className="max-w-2xl">
      <PageHeader
        title="Preferences"
        description="How much each of the six readiness factors counts towards your students' scores, for all subjects or just one. Saving a change to the factors recalculates everyone you teach."
        back={{ to: "/tutor/library", label: "Library" }}
      />

      <div className="space-y-6">
        <Field label="Settings for" className="max-w-sm">
          <Select
            value={subjectId ?? ""}
            onChange={(e) => {
              // A message about the last scope's save must not read as this one's.
              save.reset();
              remove.reset();
              setSaved(null);
              setSubjectId(e.target.value === "" ? null : Number(e.target.value));
            }}
          >
            <option value="">All subjects</option>
            {subjects.data?.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name} ({s.exam_board} {s.code})
              </option>
            ))}
          </Select>
        </Field>

        {prefs.isError ? (
          <ErrorState error={prefs.error} onRetry={() => prefs.refetch()} />
        ) : !ready ? (
          <SectionCard>
            <SectionSkeleton rows={8} label="Loading readiness settings" />
          </SectionCard>
        ) : (
          <SectionCard className="space-y-6">
            <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg bg-surface-muted px-3 py-2.5">
              <p className="text-sm text-ink-700">{sourceNote(prefs.data)}</p>
              {prefs.data.subject_id !== null && prefs.data.source !== "subject" && (
                <Button
                  variant="secondary"
                  size="sm"
                  // Saves the draft on screen — the inherited values plus any
                  // edit already made — as this subject's own override. Sending
                  // `prefs.data` would store the unedited values while the
                  // sliders kept showing the edit as if it had saved.
                  onClick={() => {
                    remove.reset();
                    save.mutate({ scope: subjectId, payload: form });
                  }}
                  disabled={save.isPending || noneEnabled || badThreshold}
                >
                  Customise for this subject
                </Button>
              )}
              {prefs.data.subject_id !== null && prefs.data.source === "subject" && (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    save.reset();
                    remove.mutate(prefs.data.subject_id!);
                  }}
                  loading={remove.isPending}
                >
                  Remove override
                </Button>
              )}
            </div>

            <fieldset className="space-y-5">
              <legend className="mb-1 text-sm font-medium text-ink-900">
                What counts, and how much
              </legend>
              {FACTORS.map((factor) => (
                <div key={factor.weight} className="space-y-1.5 border-t border-line pt-4">
                  <Slider
                    label={factor.label}
                    value={form[factor.weight]}
                    display={
                      form[factor.enabled]
                        ? `Weight ${formatWeight(form[factor.weight])}`
                        : "Switched off"
                    }
                    min={0}
                    max={3}
                    step={0.1}
                    disabled={!form[factor.enabled]}
                    onChange={(v) => setForm({ ...form, [factor.weight]: v })}
                  />
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="text-xs text-ink-500">{factor.hint}</p>
                    <label className="flex items-center gap-2 text-xs text-ink-700">
                      <input
                        type="checkbox"
                        aria-label={`Counts towards readiness: ${factor.label}`}
                        checked={form[factor.enabled]}
                        onChange={(e) => setForm({ ...form, [factor.enabled]: e.target.checked })}
                        className="h-4 w-4 accent-brand-600"
                      />
                      Counts towards readiness
                    </label>
                  </div>
                </div>
              ))}
            </fieldset>

            <div className="space-y-5 border-t border-line pt-5">
              <div className="space-y-1.5">
                <Slider
                  label="Recency half-life"
                  value={form.half_life_days}
                  display={`${form.half_life_days} days`}
                  min={7}
                  max={180}
                  step={1}
                  onChange={(v) => setForm({ ...form, half_life_days: v })}
                />
                <p className="text-xs text-ink-500">
                  How long it takes a piece of evidence to count half as much as something new.
                </p>
              </div>
              {/* Spelled out rather than a <Field>: the box is a few digits wide
                  while its hint runs the full width, and Field sizes both alike. */}
              <div>
                <label htmlFor="weak-threshold" className="block text-sm font-medium text-ink-900">
                  Weak topic threshold (%)
                </label>
                <div className="mt-1.5 w-24">
                  <Input
                    id="weak-threshold"
                    type="number"
                    min={0}
                    max={100}
                    step={1}
                    aria-invalid={badThreshold || undefined}
                    aria-describedby={badThreshold ? "weak-threshold-error" : "weak-threshold-hint"}
                    value={Number.isNaN(form.weak_threshold) ? "" : form.weak_threshold}
                    onChange={(e) => setForm({ ...form, weak_threshold: e.target.valueAsNumber })}
                    className="tabular-nums"
                  />
                </div>
                {badThreshold ? (
                  <p
                    id="weak-threshold-error"
                    role="alert"
                    className="mt-1.5 text-xs text-risk-600"
                  >
                    Enter a threshold from 0 to 100.
                  </p>
                ) : (
                  <p id="weak-threshold-hint" className="mt-1.5 text-xs text-ink-500">
                    Topics at or below this mastery score are shown as weak. Takes effect straight
                    away; no scores are recalculated.
                  </p>
                )}
              </div>
            </div>

            <p className="text-xs leading-relaxed text-ink-500">
              A higher weight counts that factor more; a shorter half-life lets recent evidence take
              over faster. A factor with no evidence is left out of the score rather than counted as
              zero. A switched-off factor never counts, but is still worked out and kept, so nothing
              is lost if you switch it back on.
            </p>

            <div className="flex flex-wrap items-center gap-3 border-t border-line pt-4">
              <Button
                onClick={() => {
                  remove.reset();
                  save.mutate({ scope: subjectId, payload: form });
                }}
                disabled={noneEnabled || badThreshold}
                loading={save.isPending}
              >
                Save
              </Button>
              {saved && (
                <span role="status" className="text-sm text-ok-700">
                  {saved === "rescoring" ? "Saved — recomputing readiness…" : "Saved."}
                </span>
              )}
              {noneEnabled && (
                <span className="text-sm text-risk-600">Keep at least one factor switched on.</span>
              )}
            </div>
            {/* One line for both actions, so each resets the other's failure
                when it starts: the line then always speaks for the last one
                tried — a failed removal is not reported as a failed save. */}
            {(save.isError || remove.isError) && (
              <p className="text-sm text-risk-600" role="alert">
                {remove.isError ? "That override wasn't removed." : "That didn't save."}{" "}
                {friendlyError(
                  remove.isError ? remove.error : save.error,
                  "Try again in a moment.",
                )}
              </p>
            )}
          </SectionCard>
        )}
      </div>
    </div>
  );
}
