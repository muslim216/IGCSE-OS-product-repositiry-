import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  addPlanBreak,
  deletePlanBreak,
  getPlan,
  savePlanInputs,
  type PlanOverview,
} from "../api/teachingPlan";
import { friendlyError } from "../lib/errors";
import { SectionCard } from "../components/ui";
import { Button, Field, Input } from "../components/controls";
import { ErrorState, SectionSkeleton } from "../components/page";

type Draft = {
  exam_date: string;
  lessons_per_week: string;
  lesson_minutes: string;
  past_paper_start_date: string;
};

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "2027-05-10" -> "10 May 2027" from the parts: a bare date is not an instant,
 *  and `new Date()` would shift it by the viewer's timezone. */
function humanDate(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  return MONTHS[m - 1] ? `${d} ${MONTHS[m - 1]} ${y}` : iso;
}

type BreakForm = { start_date: string; end_date: string; label: string };
const EMPTY_BREAK: BreakForm = { start_date: "", end_date: "", label: "" };

const FROM_TIMETABLE = "From your timetable";

/** Where a blank form starts: the saved draft, else the timetable's numbers.
 *  A missing value stays an empty string, never 0 (`PROD-2`). */
function startingValues(plan: PlanOverview): Draft {
  const saved = plan.draft;
  const defaults = plan.timetable_defaults;
  return {
    exam_date: saved?.exam_date ?? "",
    lessons_per_week: String(saved?.lessons_per_week ?? defaults.lessons_per_week ?? ""),
    lesson_minutes: String(saved?.lesson_minutes ?? defaults.lesson_minutes ?? ""),
    past_paper_start_date: saved?.past_paper_start_date ?? "",
  };
}

/** The class's teaching-plan inputs (task 6.2): exam date, pace, past-paper
 *  start and holidays. Saved onto the class's draft plan, never a live one. */
export default function TeachingPlanInputs({ groupId }: { groupId: number }) {
  const queryClient = useQueryClient();
  const plan = useQuery({ queryKey: ["plan", groupId], queryFn: () => getPlan(groupId) });
  // Only what the tutor has typed; everything else is read from the server
  // query, so a refetch is never shadowed by a stale copy (FE-6).
  const [edits, setEdits] = useState<Partial<Draft>>({});
  const [breakForm, setBreakForm] = useState<BreakForm>(EMPTY_BREAK);
  const [error, setError] = useState<string | null>(null);

  const onSettled = () => {
    // Saved inputs are what makes the plan-details onboarding step done.
    void queryClient.invalidateQueries({ queryKey: ["onboarding"] });
    return queryClient.invalidateQueries({ queryKey: ["plan", groupId] });
  };
  const save = useMutation({
    mutationFn: (v: Draft) =>
      savePlanInputs(groupId, {
        exam_date: v.exam_date,
        lessons_per_week: Number(v.lessons_per_week),
        lesson_minutes: Number(v.lesson_minutes),
        past_paper_start_date: v.past_paper_start_date || null,
      }),
    onMutate: () => setError(null),
    onSuccess: (saved, submitted) => {
      // Seed the cache from the response so the saved values show at once and
      // survive a failed refetch; clear only what was submitted, so anything
      // typed while the save was in flight is kept.
      queryClient.setQueryData(["plan", groupId], saved);
      setEdits((current) => {
        const kept: Partial<Draft> = {};
        for (const key of Object.keys(current) as (keyof Draft)[]) {
          if (current[key] !== submitted[key]) kept[key] = current[key];
        }
        return kept;
      });
    },
    onError: (err) => setError(friendlyError(err)),
    onSettled,
  });
  const addBreak = useMutation({
    mutationFn: (submitted: BreakForm) => addPlanBreak(groupId, submitted),
    onMutate: () => setError(null),
    onSuccess: (_created, submitted) =>
      // Clear only if nothing was typed while the request was pending.
      setBreakForm((current) =>
        current.start_date === submitted.start_date &&
        current.end_date === submitted.end_date &&
        current.label === submitted.label
          ? EMPTY_BREAK
          : current,
      ),
    onError: (err) => setError(friendlyError(err)),
    onSettled,
  });
  const removeBreak = useMutation({
    mutationFn: (id: number) => deletePlanBreak(groupId, id),
    onMutate: () => setError(null),
    onError: (err) => setError(friendlyError(err)),
    onSettled,
  });

  if (plan.isLoading) return <SectionSkeleton rows={3} label="Loading the teaching plan" />;
  if (plan.isError || !plan.data) {
    return (
      <ErrorState
        title="The teaching plan didn't load"
        error={plan.error}
        onRetry={() => plan.refetch()}
      />
    );
  }

  const data = plan.data;
  const values: Draft = { ...startingValues(data), ...edits };
  const set = (patch: Partial<Draft>) => setEdits((current) => ({ ...current, ...patch }));
  const defaults = data.timetable_defaults;
  // Marked only while the tutor has not touched it and no draft is saved.
  // Provenance, not equality: typing the timetable's number back in makes the
  // value theirs, so it must not be labelled as the timetable's again.
  const fromTimetable = (key: "lessons_per_week" | "lesson_minutes") =>
    !data.draft && defaults[key] != null && edits[key] === undefined ? FROM_TIMETABLE : undefined;
  const complete = Boolean(values.exam_date && values.lessons_per_week && values.lesson_minutes);
  const breaks = data.draft?.breaks ?? [];
  const breakReady = Boolean(breakForm.start_date && breakForm.end_date && breakForm.label.trim());

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    // Enter submits a form whose button is disabled; hold the same line.
    // A second save in flight could land out of order and overwrite newer edits.
    if (complete && !save.isPending) save.mutate(values);
  }

  return (
    <SectionCard>
      <h3 className="font-medium text-ink-900">Teaching plan</h3>
      <p className="mt-1 text-sm text-ink-500">
        The exam date and pace the plan is built from. Only you see these.
      </p>
      {data.accepted && (
        <p className="mt-3 rounded-md bg-surface-muted px-3 py-2 text-sm text-ink-700">
          A plan is already accepted for the exam on {humanDate(data.accepted.exam_date)}. Changes
          here are saved as a new draft and do not alter it.
        </p>
      )}
      {error && (
        <p role="alert" className="mt-3 rounded-md bg-risk-100 px-3 py-2 text-sm text-risk-600">
          {error}
        </p>
      )}

      <form onSubmit={onSubmit} className="mt-4">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Field label="Exam date">
            <Input
              type="date"
              value={values.exam_date}
              onChange={(e) => set({ exam_date: e.target.value })}
            />
          </Field>
          <Field
            label="Lessons per week"
            hint={
              fromTimetable("lessons_per_week") ??
              (defaults.lessons_per_week == null ? "No timetable yet, enter it" : undefined)
            }
          >
            <Input
              type="number"
              min={1}
              max={14}
              value={values.lessons_per_week}
              onChange={(e) => set({ lessons_per_week: e.target.value })}
            />
          </Field>
          <Field
            label="Lesson length (minutes)"
            hint={
              fromTimetable("lesson_minutes") ??
              (defaults.lesson_minutes == null ? "No timetable yet, enter it" : undefined)
            }
          >
            <Input
              type="number"
              min={15}
              max={300}
              value={values.lesson_minutes}
              onChange={(e) => set({ lesson_minutes: e.target.value })}
            />
          </Field>
          <Field label="Past papers start" optional>
            <Input
              type="date"
              value={values.past_paper_start_date}
              onChange={(e) => set({ past_paper_start_date: e.target.value })}
            />
          </Field>
        </div>
        <div className="mt-4 flex justify-end">
          <Button type="submit" disabled={!complete} loading={save.isPending}>
            Save plan inputs
          </Button>
        </div>
      </form>

      <div className="mt-6 border-t border-line pt-4">
        <h4 className="text-sm font-medium text-ink-900">Holidays and breaks</h4>
        {!data.draft ? (
          <p className="mt-1 text-sm text-ink-500">Save the plan inputs first, then add breaks.</p>
        ) : (
          <>
            {breaks.length === 0 ? (
              <p className="mt-1 text-sm text-ink-500">No breaks added.</p>
            ) : (
              <ul className="mt-2 divide-y divide-line rounded-lg border border-line">
                {breaks.map((b) => (
                  <li key={b.id} className="flex items-center justify-between gap-3 px-3 py-2">
                    <span className="text-sm text-ink-700">
                      <span className="font-medium text-ink-900">{b.label}</span>{" "}
                      <span className="tabular-nums text-ink-500">
                        {b.start_date === b.end_date
                          ? b.start_date
                          : `${b.start_date} to ${b.end_date}`}
                      </span>
                    </span>
                    <Button
                      variant="ghost"
                      size="sm"
                      disabled={removeBreak.isPending}
                      aria-label={`Remove the ${b.label} break`}
                      onClick={() => removeBreak.mutate(b.id)}
                    >
                      Remove
                    </Button>
                  </li>
                ))}
              </ul>
            )}
            <form
              className="mt-3 grid gap-4 sm:grid-cols-2 lg:grid-cols-4"
              onSubmit={(e) => {
                e.preventDefault();
                if (breakReady && !addBreak.isPending) addBreak.mutate(breakForm);
              }}
            >
              <Field label="Break starts">
                <Input
                  type="date"
                  value={breakForm.start_date}
                  onChange={(e) => setBreakForm({ ...breakForm, start_date: e.target.value })}
                />
              </Field>
              <Field label="Break ends">
                <Input
                  type="date"
                  value={breakForm.end_date}
                  onChange={(e) => setBreakForm({ ...breakForm, end_date: e.target.value })}
                />
              </Field>
              <Field label="Label">
                <Input
                  placeholder="e.g. Easter"
                  maxLength={120}
                  value={breakForm.label}
                  onChange={(e) => setBreakForm({ ...breakForm, label: e.target.value })}
                />
              </Field>
              <div className="flex items-end">
                <Button type="submit" disabled={!breakReady} loading={addBreak.isPending}>
                  Add break
                </Button>
              </div>
            </form>
          </>
        )}
      </div>
    </SectionCard>
  );
}
