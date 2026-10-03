import { useEffect, useRef, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { recordLesson } from "../api/lessons";
import { listTopics } from "../api/syllabus";
import { getNextLesson } from "../api/teachingPlan";
import { friendlyError } from "../lib/errors";
import { SectionCard } from "../components/ui";
import { Button, Field, Input } from "../components/controls";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

/** "2026-10-13" -> "Tue 13 Oct", from the parts: a bare date is not an instant. */
function plannedDate(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  const weekday = WEEKDAYS[new Date(Date.UTC(y, m - 1, d)).getUTCDay()];
  return `${weekday} ${d} ${MONTHS[m - 1]}`;
}

function today(): string {
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

/** Record a lesson that was taught. The accepted plan pre-fills the date and
 *  the topics from its next unstarted slot (`AV-17`); everything stays
 *  editable, and nothing is created until the tutor submits. */
export default function RecordLessonForm({
  groupId,
  subjectId,
}: {
  groupId: number;
  subjectId: number;
}) {
  const queryClient = useQueryClient();
  const next = useQuery({
    queryKey: ["next-lesson", groupId],
    queryFn: () => getNextLesson(groupId),
  });
  const topics = useQuery({
    queryKey: ["topics", subjectId],
    queryFn: () => listTopics(subjectId),
  });
  const suggestion = next.data ?? null;

  const [date, setDate] = useState(today());
  const [topicIds, setTopicIds] = useState<number[]>([]);
  const [notes, setNotes] = useState("");
  const [dismissed, setDismissed] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  // Pre-fill once per suggested slot. Keyed on the slot, so a refetch that
  // returns the same slot never overwrites what the tutor has since changed.
  const prefilled = useRef<number | null>(null);
  useEffect(() => {
    if (!suggestion || prefilled.current === suggestion.slot_id) return;
    prefilled.current = suggestion.slot_id;
    setDismissed(false);
    setDate(suggestion.scheduled_date);
    setTopicIds(suggestion.topics.map((t) => t.id));
  }, [suggestion]);

  const usingPlan = suggestion !== null && !dismissed;

  const save = useMutation({
    mutationFn: () =>
      recordLesson({
        group_id: groupId,
        date,
        // The server's own default; the generated type makes the field required.
        duration_min: 60,
        topic_ids: topicIds,
        notes: notes.trim() || null,
        // Only when the tutor kept the suggestion: that is what confirms the slot.
        ...(usingPlan ? { plan_slot_id: suggestion.slot_id } : {}),
      }),
    onMutate: () => {
      setError(null);
      setSaved(false);
    },
    onSuccess: () => {
      setSaved(true);
      setNotes("");
      setTopicIds([]);
      prefilled.current = null;
      queryClient.invalidateQueries({ queryKey: ["next-lesson", groupId] });
      queryClient.invalidateQueries({ queryKey: ["plan", groupId] });
    },
    onError: (err) => setError(friendlyError(err)),
  });

  function toggle(id: number) {
    setTopicIds((ids) => (ids.includes(id) ? ids.filter((i) => i !== id) : [...ids, id]));
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    save.mutate();
  }

  return (
    <SectionCard>
      <form onSubmit={onSubmit}>
        <h3 className="font-medium text-ink-900">Record a lesson you taught</h3>
        <p className="mt-1 text-sm text-ink-500">
          The topics you tick count as taught for every student in the class.
        </p>

        {usingPlan && (
          <div className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-md bg-brand-50 px-3 py-2 text-sm text-brand-700">
            <span>
              Suggested by your plan: Chapter {suggestion.chapter.code} · {suggestion.chapter.title}{" "}
              (planned {plannedDate(suggestion.scheduled_date)})
            </span>
            <Button
              type="button"
              size="sm"
              variant="ghost"
              onClick={() => {
                setDismissed(true);
                setTopicIds([]);
                setDate(today());
              }}
            >
              Don't use the plan suggestion
            </Button>
          </div>
        )}

        <div className="mt-4 grid gap-4 sm:grid-cols-2">
          <Field label="Date">
            <Input type="date" required value={date} onChange={(e) => setDate(e.target.value)} />
          </Field>
          <Field label="Notes" optional>
            <Input value={notes} onChange={(e) => setNotes(e.target.value)} />
          </Field>
        </div>

        <fieldset className="mt-4">
          <legend className="text-sm font-medium text-ink-900">Topics covered</legend>
          {topics.isLoading ? (
            <p className="mt-2 text-sm text-ink-500">Loading topics…</p>
          ) : topics.isError ? (
            <p role="alert" className="mt-2 text-sm text-risk-600">
              {friendlyError(topics.error)}
            </p>
          ) : (topics.data ?? []).length === 0 ? (
            <p className="mt-2 text-sm text-ink-500">
              This subject has no topics yet. Add its syllabus first.
            </p>
          ) : (
            <ul className="mt-2 max-h-64 space-y-1 overflow-y-auto">
              {(topics.data ?? []).map((t) => (
                <li key={t.id}>
                  <label className="flex items-center gap-2 text-sm text-ink-700">
                    <input
                      type="checkbox"
                      checked={topicIds.includes(t.id)}
                      onChange={() => toggle(t.id)}
                    />
                    <span className="tabular-nums text-ink-500">{t.code}</span> {t.title}
                  </label>
                </li>
              ))}
            </ul>
          )}
        </fieldset>

        {error && (
          <p role="alert" className="mt-3 rounded-md bg-risk-100 px-3 py-2 text-sm text-risk-600">
            {error}
          </p>
        )}
        {saved && (
          <p role="status" className="mt-3 text-sm text-ok-700">
            Lesson recorded.
          </p>
        )}
        <div className="mt-4 flex justify-end">
          <Button type="submit" loading={save.isPending}>
            Record lesson
          </Button>
        </div>
      </form>
    </SectionCard>
  );
}
