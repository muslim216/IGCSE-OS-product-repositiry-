import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getPreferences, updatePreferences, type Preferences } from "../api/readiness";

const DEFAULTS: Preferences = {
  weight_mock: 1.5,
  weight_homework: 1.0,
  weight_quiz: 0.8,
  weight_observation: 0.5,
  half_life_days: 45,
};

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
  const prefs = useQuery({ queryKey: ["preferences"], queryFn: getPreferences });
  const [form, setForm] = useState<Preferences>(DEFAULTS);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (prefs.data) setForm(prefs.data);
  }, [prefs.data]);

  const save = useMutation({
    mutationFn: () => updatePreferences(form),
    onSuccess: (data) => {
      queryClient.setQueryData(["preferences"], data);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    },
  });

  return (
    <div className="max-w-xl space-y-4">
      <div>
        <h2 className="text-xl font-semibold text-slate-800">Preferences</h2>
        <p className="text-sm text-slate-500">
          Control how the readiness engine weighs different evidence for your students.
        </p>
      </div>

      <div className="space-y-5 rounded-lg border bg-white p-4">
        <Slider
          label="Mock exams"
          value={form.weight_mock}
          min={0}
          max={3}
          step={0.1}
          onChange={(v) => setForm({ ...form, weight_mock: v })}
        />
        <Slider
          label="Homework"
          value={form.weight_homework}
          min={0}
          max={3}
          step={0.1}
          onChange={(v) => setForm({ ...form, weight_homework: v })}
        />
        <Slider
          label="Quizzes"
          value={form.weight_quiz}
          min={0}
          max={3}
          step={0.1}
          onChange={(v) => setForm({ ...form, weight_quiz: v })}
        />
        <Slider
          label="Your observations"
          value={form.weight_observation}
          min={0}
          max={3}
          step={0.1}
          onChange={(v) => setForm({ ...form, weight_observation: v })}
        />
        <Slider
          label="Recency half-life (days)"
          value={form.half_life_days}
          min={7}
          max={180}
          step={1}
          onChange={(v) => setForm({ ...form, half_life_days: v })}
        />
        <p className="text-xs text-slate-400">
          Higher weights count that evidence more; a shorter half-life makes recent evidence
          dominate faster.
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
