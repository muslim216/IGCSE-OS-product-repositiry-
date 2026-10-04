import { useEffect, useRef, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { myOrganization } from "../api/auth";
import { listLessons } from "../api/groups";
import { recordLesson } from "../api/lessons";
import { listTopics } from "../api/syllabus";
import { getNextLesson, getPlan, type NextLesson } from "../api/teachingPlan";
import { useMyTimezone } from "../auth/AuthContext";
import { friendlyError } from "../lib/errors";
import { dayKeyIn } from "../lib/timezones";
import { SectionCard } from "../components/ui";
import { Button, Field, Input, Select } from "../components/controls";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const FALLBACK_MINUTES = 60;

/** "2026-10-13" -> "Tue 13 Oct", from the parts: a bare date is not an instant. */
function plannedDate(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  const weekday = WEEKDAYS[new Date(Date.UTC(y, m - 1, d)).getUTCDay()];
  return `${weekday} ${d} ${MONTHS[m - 1]}`;
}

/** Monday = 0, matching the weekly timetable's `weekday`. */
function mondayFirstWeekday(iso: string): number {
  const [y, m, d] = iso.split("-").map(Number);
  return (new Date(Date.UTC(y, m - 1, d)).getUTCDay() + 6) % 7;
}

function suggestionLabel(s: NextLesson): string {
  return `Chapter ${s.chapter.code} · ${s.chapter.title} (planned ${plannedDate(s.scheduled_date)})`;
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
  const plan = useQuery({ queryKey: ["plan", groupId], queryFn: () => getPlan(groupId) });
  const timetable = useQuery({
    queryKey: ["lessons", groupId],
    queryFn: () => listLessons(groupId),
  });
  const suggestion = next.data ?? null;

  // "Today" is the tutor's effective day (their own zone, else the
  // organization's), not the browser's: a tutor travelling would otherwise
  // record lessons on the wrong date. Nothing is filled until it is known.
  const myZone = useMyTimezone();
  const org = useQuery({ queryKey: ["my-organization"], queryFn: myOrganization });
  const zoneReady = myZone !== null || !org.isPending;
  const todayKey = zoneReady ? dayKeyIn(new Date(), myZone ?? org.data?.timezone ?? null) : "";
  // null until the tutor or a suggestion sets it; then it is today.
  const [dateSet, setDateSet] = useState<string | null>(null);
  const date = dateSet ?? todayKey;
  const [topicIds, setTopicIds] = useState<number[]>([]);
  const [notes, setNotes] = useState("");
  const [mode, setMode] = useState<"in_person" | "online">("in_person");
  // "" = unknown: the server stores NULL, never midnight.
  const [startTime, setStartTime] = useState("");
  // A Zoom or Meet link, online lessons only; the server parses and rejects others.
  const [meetingLink, setMeetingLink] = useState("");
  // null until the tutor edits it; the shown value is then the derived default.
  const [durationEdit, setDurationEdit] = useState<string | null>(null);
  // The suggested slot the form has adopted, and the one a successful save used
  // up (never offered again, so a stale cache cannot refill the form).
  const [appliedSlot, setAppliedSlot] = useState<number | null>(null);
  const [consumedSlot, setConsumedSlot] = useState<number | null>(null);
  const [dismissed, setDismissed] = useState(false);
  const [offer, setOffer] = useState<NextLesson | null>(null);
  // Set by every edit handler: a form the tutor has touched is never overwritten.
  const dirty = useRef(false);

  const usingPlan = suggestion !== null && !dismissed && suggestion.slot_id === appliedSlot;

  // Planned length, else the weekly slot on that weekday, else the class's
  // timetable default, else 60: never an invented number when one is known.
  const accepted = plan.data?.accepted ?? null;
  const weekdaySlot = date
    ? (timetable.data ?? []).find((l) => l.weekday === mondayFirstWeekday(date))
    : undefined;
  const defaultMinutes =
    accepted?.lesson_minutes ??
    weekdaySlot?.duration_min ??
    plan.data?.timetable_defaults.lesson_minutes ??
    FALLBACK_MINUTES;
  const duration = durationEdit ?? String(defaultMinutes);

  function apply(s: NextLesson) {
    setAppliedSlot(s.slot_id);
    setDismissed(false);
    setOffer(null);
    setDateSet(s.scheduled_date);
    setTopicIds(s.topics.map((t) => t.id));
    dirty.current = false;
  }

  // A new suggestion seeds an untouched form; a touched one is only offered.
  useEffect(() => {
    if (!suggestion || suggestion.slot_id === consumedSlot || suggestion.slot_id === appliedSlot) {
      return;
    }
    if (dirty.current) setOffer(suggestion);
    else apply(suggestion);
  }, [suggestion, consumedSlot, appliedSlot]);

  const save = useMutation({
    mutationFn: () =>
      recordLesson({
        group_id: groupId,
        date,
        duration_min: Number(duration),
        topic_ids: topicIds,
        notes: notes.trim() || null,
        mode,
        start_time: startTime || null,
        ...(mode === "online" && meetingLink.trim() ? { meeting_link: meetingLink.trim() } : {}),
        // Only when the tutor kept the suggestion: that is what confirms the slot.
        ...(usingPlan ? { plan_slot_id: suggestion.slot_id } : {}),
      }),
    onSuccess: () => {
      if (usingPlan) setConsumedSlot(suggestion.slot_id);
      setAppliedSlot(null);
      setDismissed(false);
      setOffer(null);
      setDateSet(null);
      setTopicIds([]);
      setNotes("");
      setMode("in_person");
      setStartTime("");
      setMeetingLink("");
      setDurationEdit(null);
      dirty.current = false;
      for (const key of [
        ["next-lesson", groupId],
        ["taught-lessons", groupId],
        ["plan", groupId],
        // Coverage is derived from taught topics (`PROD-14`), so everything that
        // shows it is stale now.
        ["analytics", groupId],
        ["class-overview", groupId],
        ["group", groupId],
        ["today"],
      ]) {
        queryClient.invalidateQueries({ queryKey: key });
      }
    },
    // The slot may have been taken elsewhere: ask again what is next.
    onError: () => queryClient.invalidateQueries({ queryKey: ["next-lesson", groupId] }),
  });

  /** Every edit goes through here: it marks the form touched and clears a stale status. */
  function edit(change: () => void) {
    dirty.current = true;
    if (save.isSuccess || save.isError) save.reset();
    change();
  }

  function toggle(id: number) {
    edit(() =>
      setTopicIds((ids) => (ids.includes(id) ? ids.filter((i) => i !== id) : [...ids, id])),
    );
  }

  const minutes = Number(duration);
  const durationValid = Number.isInteger(minutes) && minutes >= 15 && minutes <= 480;

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (durationValid) save.mutate();
  }

  return (
    <SectionCard>
      <form onSubmit={onSubmit}>
        <h2 className="text-lg text-ink-900">Record a lesson you taught</h2>
        <p className="mt-1 text-sm text-ink-500">
          The topics you tick count as taught for every student in the class.
        </p>

        {usingPlan && (
          <div className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-md bg-brand-50 px-3 py-2 text-sm text-brand-700">
            <span>Suggested by your plan: {suggestionLabel(suggestion)}</span>
            <Button
              type="button"
              size="sm"
              variant="ghost"
              onClick={() => {
                setDismissed(true);
                dirty.current = true;
                setTopicIds([]);
                setDateSet(null);
              }}
            >
              Don't use the plan suggestion
            </Button>
          </div>
        )}
        {offer && offer.slot_id !== appliedSlot && (
          <div className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-md bg-brand-50 px-3 py-2 text-sm text-brand-700">
            <span>Your plan now suggests {suggestionLabel(offer)}</span>
            <Button type="button" size="sm" variant="ghost" onClick={() => apply(offer)}>
              Apply
            </Button>
          </div>
        )}

        <div className="mt-4 grid gap-4 sm:grid-cols-3">
          <Field label="Mode">
            <Select
              value={mode}
              onChange={(e) => edit(() => setMode(e.target.value as "in_person" | "online"))}
            >
              <option value="in_person">In person</option>
              <option value="online">Online</option>
            </Select>
          </Field>
          <Field label="Starts at" optional>
            <Input
              type="time"
              value={startTime}
              onChange={(e) => edit(() => setStartTime(e.target.value))}
            />
          </Field>
          <Field label="Date">
            <Input
              type="date"
              required
              value={date}
              onChange={(e) => edit(() => setDateSet(e.target.value))}
            />
          </Field>
          <Field label="Duration (min)">
            <Input
              type="number"
              min={15}
              max={480}
              step={5}
              required
              value={duration}
              onChange={(e) => edit(() => setDurationEdit(e.target.value))}
            />
          </Field>
          {mode === "online" && (
            <Field label="Meeting link" optional hint="Zoom or Google Meet, to fill in attendance">
              <Input
                type="url"
                value={meetingLink}
                placeholder="https://zoom.us/j/…"
                onChange={(e) => edit(() => setMeetingLink(e.target.value))}
              />
            </Field>
          )}
          <Field label="Notes" optional>
            <Input value={notes} onChange={(e) => edit(() => setNotes(e.target.value))} />
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

        {save.isError && (
          <p role="alert" className="mt-3 rounded-md bg-risk-100 px-3 py-2 text-sm text-risk-600">
            {friendlyError(save.error)}
          </p>
        )}
        {save.isSuccess && (
          <p role="status" className="mt-3 text-sm text-ok-700">
            Lesson recorded.
          </p>
        )}
        <div className="mt-4 flex justify-end">
          <Button
            type="submit"
            loading={save.isPending}
            // While the suggestion refetches the slot may be stale: a fast second
            // submit must not reuse the one just consumed.
            disabled={next.isFetching || !durationValid || !date}
          >
            Record lesson
          </Button>
        </div>
      </form>
    </SectionCard>
  );
}
