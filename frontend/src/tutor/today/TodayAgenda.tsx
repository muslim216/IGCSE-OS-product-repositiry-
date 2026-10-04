import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { AgendaItem } from "../../api/today";
import { cancelPlanSlot } from "../../api/teachingPlan";
import { friendlyError } from "../../lib/errors";
import { Button } from "../../components/controls";

/** A reminder shows from this long before the lesson starts (task 7.4, AV-120). */
const REMINDER_LEAD_MS = 15 * 60_000;

/** "in 12 min" in the lead-up, "under way" once started; null outside both, so a
    lesson hours away carries no countdown. Computed from the instant the server
    sent, so it is right whatever zone the browser is in. */
function whenLabel(
  startsAt: string | null | undefined,
  endsAt: string | null | undefined,
  now: number,
): string | null {
  if (!startsAt) return null;
  const start = new Date(startsAt).getTime();
  if (endsAt && now >= new Date(endsAt).getTime()) return null;
  if (now >= start) return "under way";
  if (start - now > REMINDER_LEAD_MS) return null;
  const minutes = Math.ceil((start - now) / 60_000);
  return minutes === 1 ? "in 1 min" : `in ${minutes} min`;
}

function planLine(item: AgendaItem): string {
  if (!item.chapter_code) return "Not part of a teaching plan";
  const topics = item.topics.map((t) => t.title).join(", ");
  return `Plan: Chapter ${item.chapter_code} · ${item.chapter_title}${topics ? ` — ${topics}` : ""}`;
}

function Row({
  item,
  now,
  onNotice,
}: {
  item: AgendaItem;
  now: number;
  onNotice: (message: string | null) => void;
}) {
  const queryClient = useQueryClient();
  const cancel = useMutation({
    mutationFn: () => cancelPlanSlot(item.group_id, item.slot_id as number),
    onSuccess: (result) => {
      // Lifted out because this row is gone on the refetch below, and its own
      // message with it (no room before the exam: nothing moved).
      onNotice(result.shifted ? null : (result.message ?? null));
      for (const key of [
        ["today-overview"],
        ["lesson-reminders"],
        ["plan", item.group_id],
        ["next-lesson"],
        ["today"],
      ]) {
        queryClient.invalidateQueries({ queryKey: key });
      }
    },
  });
  const ended = item.ends_at != null && now >= new Date(item.ends_at).getTime();
  const classLink = `/tutor/groups/${item.group_id}/schedule`;
  // Recording is always dated today and, when the lesson has a slot, pre-filled
  // from that slot — never from the plan's next unstarted (future) one (C.3).
  const recordHref = `${classLink}?${item.slot_id != null ? `slot=${item.slot_id}&` : ""}date=${item.local_date}`;
  const soon = item.recorded ? null : whenLabel(item.starts_at, item.ends_at, now);

  let action: React.ReactNode = null;
  if (item.recorded) {
    action = (
      <span className="flex items-center gap-3">
        <span className="text-ok-700">Recorded</span>
        <Link
          to={classLink}
          aria-label={`Take attendance for the ${item.group_name} lesson`}
          className="font-medium text-brand-600 hover:text-brand-700"
        >
          Take attendance →
        </Link>
      </span>
    );
  } else if (ended) {
    action = (
      <Link
        to={recordHref}
        aria-label={`Record the ${item.group_name} lesson, dated today`}
        className="font-medium text-brand-600 hover:text-brand-700"
      >
        Record →
      </Link>
    );
  } else if (item.slot_id != null) {
    action = (
      <span className="flex items-center gap-2">
        <Link
          to={recordHref}
          aria-label={`Review the ${item.group_name} lesson`}
          className="font-medium text-brand-600 hover:text-brand-700"
        >
          Review →
        </Link>
        <Button
          type="button"
          size="sm"
          variant="ghost"
          aria-label={`Cancel the ${item.group_name} lesson`}
          loading={cancel.isPending}
          onClick={() => cancel.mutate()}
        >
          Cancel
        </Button>
      </span>
    );
  }

  return (
    <li className="border-t border-line py-3 text-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-ink-700">
          <span className="font-display tabular-nums text-ink-900">
            {item.start_time ? item.start_time.slice(0, 5) : "Time not set"}
          </span>{" "}
          <Link
            to={`/tutor/groups/${item.group_id}/students`}
            className="font-medium text-ink-900 hover:text-brand-600"
          >
            {item.group_name}
          </Link>{" "}
          <span className="text-ink-500">{item.subject_name}</span>
          {soon && <> · {soon}</>}
          <span className="block text-ink-500">{planLine(item)}</span>
        </span>
        {action}
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
 * Today's lessons, each with what the plan covers and one action:
 * before or around the start, Review and Cancel; once it has ended and nobody
 * recorded it, Record (dated today); recorded, "Recorded" and a way to take
 * attendance. This one list replaces the separate "starting soon" reminder and
 * the timetable-only Today block; the 15-minute reminder is the "in N min" /
 * "under way" wording on the row itself.
 */
export default function TodayAgenda({ items }: { items: AgendaItem[] }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 30_000);
    return () => clearInterval(id);
  }, []);
  const [notice, setNotice] = useState<string | null>(null);
  return (
    <section aria-labelledby="agenda-heading">
      <h2 id="agenda-heading" className="avora-label mb-3">
        Today
      </h2>
      {notice && (
        <p role="status" className="border-t border-line py-2.5 text-sm text-ink-700">
          {notice}
        </p>
      )}
      {items.length === 0 ? (
        <p className="text-sm text-ink-500">No lessons scheduled today.</p>
      ) : (
        <ul>
          {items.map((item) => (
            <Row key={item.key} item={item} now={now} onNotice={setNotice} />
          ))}
        </ul>
      )}
    </section>
  );
}
