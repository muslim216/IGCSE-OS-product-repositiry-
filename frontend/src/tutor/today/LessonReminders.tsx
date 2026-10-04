import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { lessonReminders, type LessonReminder } from "../../api/today";
import { cancelPlanSlot } from "../../api/teachingPlan";
import { friendlyError } from "../../lib/errors";
import { Button } from "../../components/controls";

const POLL_MS = 60_000;

/** "in 12 min" before the start, "under way" after: from the instant the server
    sent, so it is right whatever zone the browser is in. */
function whenLabel(startsAt: string, now: number): string {
  const minutes = Math.ceil((new Date(startsAt).getTime() - now) / 60_000);
  if (minutes <= 0) return "under way";
  return minutes === 1 ? "in 1 min" : `in ${minutes} min`;
}

function Reminder({
  r,
  now,
  onNotice,
}: {
  r: LessonReminder;
  now: number;
  onNotice: (message: string | null) => void;
}) {
  const queryClient = useQueryClient();
  const cancel = useMutation({
    mutationFn: () => cancelPlanSlot(r.group_id, r.slot_id),
    onSuccess: (result) => {
      // No room before the exam: the lesson is cancelled, nothing moved, and the
      // tutor is told how to catch up. Lifted out because this row is gone on
      // the refetch below, and its own message with it.
      onNotice(result.shifted ? null : (result.message ?? null));
      // The cancelled lesson is gone whatever the refetch says.
      queryClient.setQueryData<LessonReminder[]>(["lesson-reminders"], (old) =>
        Array.isArray(old) ? old.filter((x) => x.slot_id !== r.slot_id) : old,
      );
      // The plan shifted (or said it could not), so everything reading it is stale.
      for (const key of [["lesson-reminders"], ["plan", r.group_id], ["next-lesson"], ["today"]]) {
        queryClient.invalidateQueries({ queryKey: key });
      }
    },
  });
  return (
    <li className="border-t border-line py-2.5 text-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-ink-700">
          <span className="font-display tabular-nums text-ink-900">{r.start_time.slice(0, 5)}</span>{" "}
          <span className="font-medium text-ink-900">{r.group_name}</span> ·{" "}
          {whenLabel(r.starts_at, now)}
          <span className="block text-ink-500">
            Plan: Chapter {r.chapter.code} · {r.chapter.title}
            {r.topics.length > 0 && <> — {r.topics.map((t) => t.title).join(", ")}</>}
          </span>
        </span>
        <span className="flex items-center gap-2">
          <Link
            to={`/tutor/groups/${r.group_id}/schedule?slot=${r.slot_id}`}
            aria-label={`Review the ${r.group_name} lesson`}
            className="font-medium text-brand-600 hover:text-brand-700"
          >
            Review →
          </Link>
          <Button
            type="button"
            size="sm"
            variant="ghost"
            aria-label={`Cancel the ${r.group_name} lesson`}
            loading={cancel.isPending}
            onClick={() => cancel.mutate()}
          >
            Cancel
          </Button>
        </span>
      </div>
      {cancel.isError && (
        <p role="alert" className="mt-2 text-risk-600">
          {friendlyError(cancel.error)}
        </p>
      )}
    </li>
  );
}

/**
 * Planned lessons starting within 15 minutes, or under way (task 7.4, AV-120).
 * In-app only: computed server-side from the accepted plan at read time, so
 * there is nothing to dismiss or clear. Review opens the record form pre-filled
 * with what the plan says; Cancel is one tap and shifts the plan. Renders
 * nothing when there is no reminder, or when it cannot be loaded — it is
 * information, never a gate (UX-29).
 */
export default function LessonReminders() {
  const reminders = useQuery({
    queryKey: ["lesson-reminders"],
    queryFn: lessonReminders,
    refetchInterval: POLL_MS,
  });
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 30_000);
    return () => clearInterval(id);
  }, []);
  const [notice, setNotice] = useState<string | null>(null);
  // An extra on the home page: anything but a list renders nothing rather than
  // taking the page down with it.
  const rows = Array.isArray(reminders.data) ? reminders.data : [];
  // A failed check is not "nothing starting soon" (PROD-2): say so, quietly, even
  // when older rows are still cached (they may be stale).
  const failed = reminders.isError ? (
    <p role="status" className="flex items-center gap-2 text-sm text-ink-500">
      Couldn&apos;t check for upcoming lessons.
      <Button type="button" size="sm" variant="ghost" onClick={() => reminders.refetch()}>
        Retry
      </Button>
    </p>
  ) : null;
  if (rows.length === 0 && !notice) return failed;
  return (
    <section aria-labelledby="lesson-reminders-heading">
      <h2 id="lesson-reminders-heading" className="avora-label mb-3">
        Starting soon
      </h2>
      {notice && (
        <p role="status" className="border-t border-line py-2.5 text-sm text-ink-700">
          {notice}
        </p>
      )}
      {failed}
      <ul>
        {rows.map((r) => (
          <Reminder key={r.slot_id} r={r} now={now} onNotice={setNotice} />
        ))}
      </ul>
    </section>
  );
}
