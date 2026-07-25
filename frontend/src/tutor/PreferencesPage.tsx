import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  getReadinessWeights,
  updateReadinessWeights,
  type ReadinessWeights,
} from "../api/readiness";

const DEFAULTS: ReadinessWeights = {
  weight_topic_mastery: 1,
  weight_past_paper_performance: 1,
  weight_homework_performance: 1,
  weight_assessment_performance: 1,
  weight_syllabus_coverage: 1,
  weight_mistake_analysis: 1,
  weight_consistency: 1,
  half_life_days: 45,
};

/** The seven factors the Readiness Engine scores, in the order a tutor is
 * most likely to care about them. */
const FACTORS: { key: keyof ReadinessWeights; label: string; hint: string }[] = [
  {
    key: "weight_topic_mastery",
    label: "Topic mastery",
    hint: "Per-topic marks from classifieds and homework",
  },
  {
    key: "weight_past_paper_performance",
    label: "Past paper performance",
    hint: "Full papers under exam conditions",
  },
  {
    key: "weight_homework_performance",
    label: "Homework performance",
    hint: "Overall homework marks",
  },
  {
    key: "weight_assessment_performance",
    label: "Assessment performance",
    hint: "Mocks and class tests",
  },
  {
    key: "weight_syllabus_coverage",
    label: "Syllabus coverage",
    hint: "How much of the syllabus has been taught and evidenced",
  },
  {
    key: "weight_mistake_analysis",
    label: "Mistake analysis",
    hint: "Recurring mistakes and their severity",
  },
  {
    key: "weight_consistency",
    label: "Consistency",
    hint: "How steady their performance is over time",
  },
];

function Slider({
  label,
  value,
  min,
  max,
  step,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  onChange: (v: number) => void;
}) {
  return (
    <div>
      <div className="flex items-center justify-between text-sm">
        <label className="font-medium text-slate-700">{label}</label>
        <span className="text-slate-500">{value}</span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="mt-1 w-full accent-cyan-400"
      />
    </div>
  );
}

export default function PreferencesPage() {
  const queryClient = useQueryClient();
  const prefs = useQuery({
    queryKey: ["readiness-weights"],
    queryFn: getReadinessWeights,
  });
  const [form, setForm] = useState<ReadinessWeights>(DEFAULTS);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (prefs.data) setForm(prefs.data);
  }, [prefs.data]);

  const save = useMutation({
    mutationFn: () => updateReadinessWeights(form),
    onSuccess: (data) => {
      queryClient.setQueryData(["readiness-weights"], data);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    },
  });

  return (
    <div className="max-w-xl space-y-4">
      <div>
        <h2 className="text-xl font-semibold text-slate-800">Preferences</h2>
        <p className="text-sm text-slate-500">
          Control how much each of the seven readiness factors counts towards
          your students' scores. Saving recalculates everyone you teach.
        </p>
      </div>

      <div className="space-y-5 rounded-lg border bg-white p-4">
        {FACTORS.map((factor) => (
          <div key={factor.key}>
            <Slider
              label={factor.label}
              value={form[factor.key]}
              min={0}
              max={3}
              step={0.1}
              onChange={(v) => setForm({ ...form, [factor.key]: v })}
            />
            <p className="text-xs text-slate-400">{factor.hint}</p>
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
        <p className="text-xs text-slate-400">
          Higher weights count that factor more; a shorter half-life makes recent
          evidence dominate faster. A factor with no evidence is weighed out of
          the score rather than counted as zero.
        </p>

        <div className="flex items-center gap-3">
          <button
            onClick={() => save.mutate()}
            disabled={save.isPending}
            className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {save.isPending ? "Saving…" : "Save"}
          </button>
          {saved && <span className="text-sm text-green-700">Saved — recomputing readiness…</span>}
        </div>
      </div>
    </div>
  );
}
