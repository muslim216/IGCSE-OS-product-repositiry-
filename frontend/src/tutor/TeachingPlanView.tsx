import { useCallback, useEffect, useId, useRef, useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  acceptPlan,
  cancelPlanSlot,
  draftPlan,
  editPlanSlot,
  getPlan,
  replanPlan,
  type DraftOutcome,
  type PlanInputs,
  type PlanProgress,
  type ReflowOutcome,
  type PlanSlot,
} from "../api/teachingPlan";
import { myOrganization } from "../api/auth";
import { useMyTimezone } from "../auth/AuthContext";
import { listChapters, type Chapter } from "../api/syllabus";
import { Check, MoreHorizontal } from "lucide-react";
import { friendlyError } from "../lib/errors";
import { shortDay } from "../lib/planDates";
import { dayKeyIn } from "../lib/timezones";
import { SectionCard } from "../components/ui";
import { Button, Input, Select } from "../components/controls";
import { ConfirmDialog, ErrorState, SectionSkeleton } from "../components/page";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const POLL_MS = 3000;

/** "2027-05-10" -> "10 May 2027", from the parts: a bare date is not an instant. */
function humanDate(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  return MONTHS[m - 1] ? `${d} ${MONTHS[m - 1]} ${y}` : iso;
}

/** An instant shown as a date in the viewer's own zone (the tutor's, here). */
function localDate(instant: string): string {
  return new Date(instant).toLocaleDateString(undefined, {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

/** "17:00:00" -> "17:00". null stays null: an unknown time is not midnight. */
function hhmm(time: string | null | undefined): string | null {
  return time ? time.slice(0, 5) : null;
}

type SlotPatch = { scheduled_date?: string; chapter_id?: number; start_time?: string };

/** The Monday of the ISO date's week, as an ISO date (UTC arithmetic, no timezone drift). */
function weekStart(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  const date = new Date(Date.UTC(y, m - 1, d));
  date.setUTCDate(date.getUTCDate() - ((date.getUTCDay() + 6) % 7));
  return date.toISOString().slice(0, 10);
}

function groupByWeek(slots: PlanSlot[]): [string, PlanSlot[]][] {
  const weeks = new Map<string, PlanSlot[]>();
  for (const slot of slots) {
    const key = weekStart(slot.scheduled_date);
    weeks.set(key, [...(weeks.get(key) ?? []), slot]);
  }
  return [...weeks.entries()].sort(([a], [b]) => a.localeCompare(b));
}

/** ISO date plus whole days (UTC arithmetic, so no timezone drift). */
function addDays(iso: string, days: number): string {
  const [y, m, d] = iso.split("-").map(Number);
  const date = new Date(Date.UTC(y, m - 1, d));
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

/** Splits weeks into earlier / open / later: this week and the next three stay
 *  open. A plan with nothing in that window (a draft for next term, or one that
 *  is wholly past) still opens on something rather than showing a bare fold.
 *  `today` is the tutor's own day (their zone, else the organization's), not the
 *  browser's. */
function splitWeeks(weeks: [string, PlanSlot[]][], today: string) {
  const thisWeek = weekStart(today);
  const lastOpen = addDays(thisWeek, 21);
  let open = weeks.filter(([k]) => k >= thisWeek && k <= lastOpen);
  if (open.length === 0) {
    const firstFuture = weeks.find(([k]) => k >= thisWeek);
    open = firstFuture
      ? weeks.filter(([k]) => k >= firstFuture[0] && k <= addDays(firstFuture[0], 21))
      : weeks.slice(-1);
  }
  const first = open[0][0];
  const last = open[open.length - 1][0];
  return {
    earlier: weeks.filter(([k]) => k < first),
    open,
    later: weeks.filter(([k]) => k > last),
  };
}

type OutcomeNote = { tone: "risk" | "warn"; text: string };

/** Says plainly when the weights did not come from the AI, and why (`PROD-1`). */
function outcomeNotes(outcome: DraftOutcome | null, jobFailed: boolean): OutcomeNote[] {
  const notes: OutcomeNote[] = [];
  if (jobFailed) {
    notes.push({
      tone: "risk",
      text: "The last attempt to draft the plan did not run. Try again.",
    });
  }
  if (outcome?.status === "failed") {
    notes.push({
      tone: "risk",
      text: outcome.failure_message ?? "The plan could not be drafted.",
    });
  } else if (outcome?.status === "stale") {
    notes.push({
      tone: "warn",
      text: "Inputs changed since this draft — draft again before accepting.",
    });
  } else if (outcome?.status === "skipped") {
    notes.push({
      tone: "warn",
      text: "This draft was not generated, so there is nothing to accept. Draft the plan again.",
    });
  } else if (outcome?.status === "drafted" && outcome.weight_source !== "ai") {
    notes.push({
      tone: "warn",
      text: `These lesson counts did not come from the AI's advice. ${
        outcome.degraded_reason ?? "No reason was recorded."
      }`,
    });
  } else if (outcome?.status === "drafted" && outcome.defaulted_chapters > 0) {
    notes.push({
      tone: "warn",
      text: `${outcome.defaulted_chapters} chapter${
        outcome.defaulted_chapters === 1 ? " got a default share" : "s got a default share"
      } — the AI gave no advice for ${outcome.defaulted_chapters === 1 ? "it" : "them"}.`,
    });
  }
  return notes;
}

function OutcomeBanner({ notes }: { notes: OutcomeNote[] }) {
  return (
    <div className="mt-3 space-y-2">
      {notes.map((n) => (
        <p
          key={n.text}
          role="status"
          className={`rounded-md px-3 py-2 text-sm ${
            n.tone === "risk" ? "bg-risk-100 text-risk-600" : "bg-warn-100 text-warn-700"
          }`}
        >
          {n.text}
        </p>
      ))}
    </div>
  );
}

/** Says what the last automatic syllabus-change reflow did (task 6.8). A failure
 *  is stated; a skip and a success stay quiet. */
function ReflowNote({ reflow }: { reflow: ReflowOutcome | null | undefined }) {
  if (!reflow || !reflow.at) return null;
  const when = localDate(reflow.at);
  if (reflow.status === "failed") {
    return (
      <p role="alert" className="mt-3 rounded-md bg-risk-100 px-3 py-2 text-sm text-risk-600">
        Your syllabus changed on {when}, but the plan couldn&apos;t be reshuffled:{" "}
        {reflow.failure_message ?? "no reason was recorded."}
      </p>
    );
  }
  if (reflow.status === "skipped") {
    return (
      <p className="mt-2 text-xs text-ink-500">
        Your syllabus changed on {when}; the plan was left as it was
        {reflow.reason ? ` (${reflow.reason})` : ""}.
      </p>
    );
  }
  if (reflow.status === "reflowed") {
    return (
      <p className="mt-2 text-xs text-ink-500">Updated for your syllabus changes on {when}.</p>
    );
  }
  // An unknown status is not guessed at: say nothing rather than something false.
  return null;
}

/** Planned lessons with no recorded lesson (task 6.6, AV-18). "Not recorded" is
 *  the fact: the lesson may have been taught and never logged, so this does not
 *  blame. Its button offers a re-plan that only drafts; the tutor still accepts it. */
function behindText(progress: PlanProgress): string | null {
  if (progress.missed < 1 || !progress.earliest_missed_date) return null;
  const n = progress.missed;
  return `${n} planned ${n === 1 ? "lesson hasn't" : "lessons haven't"} been recorded since ${shortDay(
    progress.earliest_missed_date,
  )} — record ${n === 1 ? "it" : "them"}, or re-plan from today.`;
}

function SlotRow({
  slot,
  chapters,
  chaptersReady,
  chaptersError,
  onRetryChapters,
  locked,
  saving,
  onSave,
  onCancel,
  cancelling = false,
  cancelBusy = false,
  wantsFocus = false,
  onFocusDone,
  onRestoreFocus,
}: {
  slot: PlanSlot;
  chapters: Chapter[];
  /** False until the subject's chapter list has loaded: the select would be empty. */
  chaptersReady: boolean;
  /** The chapter list failed to load; said out loud rather than shown as no chapters. */
  chaptersError: boolean;
  onRetryChapters: () => void;
  /** A draft job is running and will replace generated slots under the tutor's hands. */
  locked: boolean;
  saving: boolean;
  onSave: (patch: SlotPatch, done: () => void) => void;
  /** Only the accepted plan's untaught lessons can be cancelled (AV-120). */
  onCancel?: () => void;
  cancelling?: boolean;
  /** Any cancel is in flight: the shift is one at a time, so none may start. */
  cancelBusy?: boolean;
  /** Editing ended: the row's Edit button should take focus back (the row may
   *  have been rebuilt by then, so the list remembers the request). */
  wantsFocus?: boolean;
  onFocusDone: () => void;
  onRestoreFocus: (date: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  // On a phone the row's actions sit behind a "…" button; on a wide screen hover
  // or focus reveals them. Neither path is mouse-only.
  const [menuOpen, setMenuOpen] = useState(false);
  const [date, setDate] = useState(slot.scheduled_date);
  const [chapterId, setChapterId] = useState(slot.chapter_id);
  const [startTime, setStartTime] = useState(hhmm(slot.start_time) ?? "");
  const dateLabelRef = useRef<HTMLLabelElement>(null);
  const editRef = useRef<HTMLButtonElement>(null);
  const moreRef = useRef<HTMLButtonElement>(null);
  const actionsId = useId();

  useEffect(() => {
    if (editing) dateLabelRef.current?.querySelector("input")?.focus();
  }, [editing]);
  useEffect(() => {
    if (!wantsFocus || editing) return;
    const edit = editRef.current;
    // Below md the actions are folded away until "…" opens them: focus that then.
    const shown = edit?.parentElement && getComputedStyle(edit.parentElement).display !== "none";
    (shown ? edit : moreRef.current)?.focus();
    onFocusDone();
  }, [wantsFocus, editing, onFocusDone]);

  if (editing) {
    const startChanged = startTime !== "" && startTime !== hhmm(slot.start_time);
    const changed = date !== slot.scheduled_date || chapterId !== slot.chapter_id || startChanged;
    return (
      <li className="flex flex-wrap items-end gap-3 px-3 py-2">
        <label ref={dateLabelRef} className="text-sm text-ink-700">
          <span className="block text-xs text-ink-500">Date</span>
          <Input
            type="date"
            aria-label="Lesson date"
            value={date}
            onChange={(e) => setDate(e.target.value)}
          />
        </label>
        <label className="text-sm text-ink-700">
          <span className="block text-xs text-ink-500">Starts at</span>
          <Input
            type="time"
            aria-label="Lesson start time"
            value={startTime}
            onChange={(e) => setStartTime(e.target.value)}
          />
        </label>
        <label className="min-w-40 text-sm text-ink-700">
          <span className="block text-xs text-ink-500">Chapter</span>
          <Select
            aria-label="Lesson chapter"
            disabled={!chaptersReady}
            value={chapterId}
            onChange={(e) => setChapterId(Number(e.target.value))}
          >
            {chapters.map((c) => (
              <option key={c.id} value={c.id}>
                {c.code} {c.title}
              </option>
            ))}
          </Select>
          {chaptersError && (
            <span role="alert" className="mt-1 block text-xs text-risk-600">
              The chapter list didn&apos;t load.{" "}
              <button type="button" className="underline" onClick={onRetryChapters}>
                Retry
              </button>
            </span>
          )}
        </label>
        <Button
          size="sm"
          disabled={!changed || !date}
          loading={saving}
          onClick={() =>
            onSave(
              {
                ...(date !== slot.scheduled_date ? { scheduled_date: date } : {}),
                ...(chapterId !== slot.chapter_id ? { chapter_id: chapterId } : {}),
                ...(startChanged ? { start_time: startTime } : {}),
              },
              () => {
                setEditing(false);
                onRestoreFocus(date);
              },
            )
          }
        >
          Save lesson
        </Button>
        <Button
          size="sm"
          variant="ghost"
          onClick={() => {
            setDate(slot.scheduled_date);
            setChapterId(slot.chapter_id);
            setStartTime(hhmm(slot.start_time) ?? "");
            setEditing(false);
            onRestoreFocus(slot.scheduled_date);
          }}
        >
          Cancel
        </Button>
      </li>
    );
  }
  const taught = slot.provenance === "confirmed" || slot.provenance === "completed";
  const label = humanDate(slot.scheduled_date);
  // Two lessons can share a date: the time, then the chapter, tell them apart.
  const which = `${label}${hhmm(slot.start_time) ? ` at ${hhmm(slot.start_time)}` : ""}, ${slot.chapter_code} ${slot.chapter_title}`;
  // The row's own cancel in flight keeps its actions on screen so the spinner is seen.
  const shown = menuOpen || cancelling;
  // Hidden until hover or focus only where a fine pointer can hover and no
  // touch input exists: a touch laptop with a trackpad reports a fine hovering
  // pointer, and must never be left with invisible, tappable buttons.
  const fineOnly = "[@media(hover:hover)_and_(pointer:fine)_and_(not_(any-pointer:coarse))]";
  const hoverOnly = !shown
    ? ` ${fineOnly}:opacity-0 ${fineOnly}:group-hover:opacity-100 ${fineOnly}:group-focus-within:opacity-100`
    : "";
  return (
    <li data-slot-id={slot.id} className="group flex items-center justify-between gap-3 px-3 py-2">
      <span className="min-w-0 text-sm text-ink-700">
        <span className="tabular-nums text-ink-500">
          {label}
          {hhmm(slot.start_time) && ` · ${hhmm(slot.start_time)}`}
        </span>
        {" · "}
        <span className={slot.cancelled ? "text-ink-500 line-through" : "font-medium text-ink-900"}>
          {slot.chapter_code} {slot.chapter_title}
        </span>
        {/* Status is one quiet tick, not four pills. What the old pills said is
            still said, to screen readers. Hand-edited marks a lesson a redraft
            keeps, so it is said in words (PROD-7). */}
        {taught && (
          <span className="ml-2 inline-flex align-middle text-ok-700">
            <Check aria-hidden className="h-4 w-4" />
            <span className="sr-only"> taught</span>
          </span>
        )}
        {slot.cancelled && <span className="ml-2 text-xs text-ink-500">cancelled</span>}
        {slot.lesson_origin === "plan" && <span className="sr-only"> Recorded from the plan</span>}
        {slot.provenance === "manually_modified" && (
          <span className="ml-2 text-xs text-ink-500">hand-edited</span>
        )}
      </span>
      {!slot.cancelled && (
        <span className="flex shrink-0 items-center gap-1">
          {/* On a phone the actions sit behind this button; wide screens show
              them. Neither path is mouse-only. */}
          <Button
            ref={moreRef}
            size="sm"
            variant="ghost"
            className="max-md:min-h-11 max-md:min-w-11 md:hidden"
            aria-label={`More actions, ${which}`}
            aria-expanded={menuOpen}
            aria-controls={actionsId}
            onClick={() => setMenuOpen((o) => !o)}
          >
            <MoreHorizontal aria-hidden className="h-4 w-4" />
          </Button>
          <span
            id={actionsId}
            className={`${shown ? "flex" : "hidden"} items-center gap-1 md:flex${hoverOnly}`}
          >
            {onCancel && !taught && (
              <Button
                size="sm"
                variant="ghost"
                className="max-md:min-h-11 max-md:min-w-11"
                data-slot-action
                aria-label={`Cancel lesson, ${which}`}
                disabled={locked || cancelBusy}
                loading={cancelling}
                onClick={() => {
                  setMenuOpen(false);
                  onCancel();
                }}
              >
                Cancel lesson
              </Button>
            )}
            <Button
              ref={editRef}
              size="sm"
              variant="ghost"
              className="max-md:min-h-11 max-md:min-w-11"
              data-slot-action
              aria-label={`Edit, ${which}`}
              disabled={locked}
              onClick={() => {
                // The row is no longer rebuilt when it changes, so what the
                // form starts from is read afresh each time it opens.
                setDate(slot.scheduled_date);
                setChapterId(slot.chapter_id);
                setStartTime(hhmm(slot.start_time) ?? "");
                setMenuOpen(false);
                setEditing(true);
              }}
            >
              Edit
            </Button>
          </span>
        </span>
      )}
    </li>
  );
}

/** A native disclosure whose rows are not rendered until it is opened, so a
 *  year-long plan does not mount every lesson. The click is handled here rather
 *  than left to the browser so the open state is ours and the content mounts
 *  only when it shows. */
function Fold({
  label,
  children,
  wantsFocus = false,
  onFocusDone,
}: {
  label: string;
  children: ReactNode;
  /** A lesson moved in here while the fold was closed: its summary takes focus. */
  wantsFocus?: boolean;
  onFocusDone?: () => void;
}) {
  const [open, setOpen] = useState(false);
  const summaryRef = useRef<HTMLElement>(null);
  useEffect(() => {
    if (!wantsFocus || open) return;
    summaryRef.current?.focus();
    onFocusDone?.();
  }, [wantsFocus, open, onFocusDone]);
  return (
    <details open={open} className="mt-3">
      <summary
        ref={summaryRef}
        className="cursor-pointer text-xs font-medium uppercase tracking-wide text-ink-500"
        onClick={(e) => {
          e.preventDefault();
          setOpen((o) => !o);
        }}
      >
        {label}
      </summary>
      {open && children}
    </details>
  );
}

const weeksLabel = (n: number) => `${n} ${n === 1 ? "week" : "weeks"}`;

function SlotList({
  slots,
  chapters,
  chaptersReady,
  chaptersError,
  onRetryChapters,
  locked = false,
  saving,
  onSave,
  onCancel,
  cancellingId = null,
  cancelBusy = false,
  today,
  version,
}: {
  slots: PlanSlot[];
  chapters: Chapter[];
  chaptersReady: boolean;
  chaptersError: boolean;
  onRetryChapters: () => void;
  locked?: boolean;
  saving: boolean;
  onSave: (slotId: number, patch: SlotPatch, done: () => void) => void;
  /** `done` runs once the cancel has gone through. */
  onCancel?: (slotId: number, done: () => void) => void;
  cancellingId?: number | null;
  cancelBusy?: boolean;
  today: string;
  /** How many times the plan has been fetched: tells a stale list from a fresh one. */
  version: number;
}) {
  const { earlier, open, later } = splitWeeks(groupByWeek(slots), today);
  // Which row's Edit button gets focus back, and on which date: a save that
  // moves a lesson is only done once the list shows it on its new date.
  // A newer fetch than the one the request was made against also counts: the
  // server may have put the lesson somewhere other than where it was asked to.
  const [focusReq, setFocusReq] = useState<{
    id: number;
    date: string;
    version: number;
  } | null>(null);
  const due = (r: PlanSlot) =>
    focusReq !== null &&
    r.id === focusReq.id &&
    (r.scheduled_date === focusReq.date || version !== focusReq.version);
  const focusSlotId = focusReq?.id ?? null;
  const focusDone = useCallback(() => setFocusReq(null), []);
  const listRef = useRef<HTMLDivElement>(null);
  const inWeeks = (weeks: [string, PlanSlot[]][]) =>
    focusReq !== null && weeks.some(([, rows]) => rows.some(due));
  // A request for a lesson that is no longer anywhere (or was never shown)
  // must not wait for ever to steal focus later.
  const known = slots.some((s) => s.id === focusSlotId);
  useEffect(() => {
    if (focusSlotId !== null && !known) setFocusReq(null);
  }, [focusSlotId, known]);
  // After a cancel the row's buttons are gone: hand focus to the next lesson
  // that has actions (else the one before), decided from what is on screen now.
  const cancelAndMoveFocus = (slotId: number) => {
    const rows = Array.from(
      listRef.current?.querySelectorAll<HTMLElement>("li[data-slot-id]") ?? [],
    );
    const at = rows.findIndex((r) => r.dataset.slotId === String(slotId));
    const hasActions = (r: HTMLElement) => r.querySelector("[data-slot-action]") !== null;
    const next =
      rows.slice(at + 1).find(hasActions) ??
      rows.slice(0, Math.max(at, 0)).reverse().find(hasActions);
    onCancel?.(slotId, () => {
      const target = slots.find((x) => String(x.id) === next?.dataset.slotId);
      if (target) setFocusReq({ id: target.id, date: target.scheduled_date, version });
    });
  };
  const renderWeeks = (weeks: [string, PlanSlot[]][]) =>
    weeks.map(([week, rows]) => (
      <div key={week}>
        <h5 className="text-xs font-medium uppercase tracking-wide text-ink-500">
          Week of {humanDate(week)}
        </h5>
        <ul className="mt-1 divide-y divide-line rounded-lg border border-line">
          {rows.map((slot) => (
            <SlotRow
              key={slot.id}
              slot={slot}
              chapters={chapters}
              chaptersReady={chaptersReady}
              chaptersError={chaptersError}
              onRetryChapters={onRetryChapters}
              locked={locked}
              saving={saving}
              onSave={(patch, done) => onSave(slot.id, patch, done)}
              onCancel={onCancel ? () => cancelAndMoveFocus(slot.id) : undefined}
              cancelling={cancellingId === slot.id}
              cancelBusy={cancelBusy}
              wantsFocus={due(slot)}
              onFocusDone={focusDone}
              onRestoreFocus={(date) => setFocusReq({ id: slot.id, date, version })}
            />
          ))}
        </ul>
      </div>
    ));
  return (
    <div ref={listRef} className="mt-3 space-y-4">
      {earlier.length > 0 && (
        <Fold
          label={`Earlier: ${weeksLabel(earlier.length)}`}
          wantsFocus={inWeeks(earlier)}
          onFocusDone={focusDone}
        >
          <div className="mt-2 space-y-4">{renderWeeks(earlier)}</div>
        </Fold>
      )}
      {renderWeeks(open)}
      {later.length > 0 && (
        <Fold
          label={`Later: ${weeksLabel(later.length)}`}
          wantsFocus={inWeeks(later)}
          onFocusDone={focusDone}
        >
          <div className="mt-2 space-y-4">{renderWeeks(later)}</div>
        </Fold>
      )}
    </div>
  );
}

function Reasons({ outcome }: { outcome: DraftOutcome }) {
  if (outcome.chapters.length === 0) return null;
  return (
    <details className="mt-3 rounded-lg border border-line px-3 py-2">
      <summary className="cursor-pointer text-sm font-medium text-ink-900">
        Why each chapter got its share
      </summary>
      <ul className="mt-2 space-y-1 text-sm text-ink-700">
        {outcome.chapters.map((c) => (
          <li key={c.chapter_id}>
            <span className="font-medium text-ink-900">
              {c.chapter_code ?? "Chapter"} {c.chapter_title ?? "(removed)"}
            </span>{" "}
            <span className="tabular-nums text-ink-500">weight {c.weight}</span>
            {c.reason ? ` — ${c.reason}` : ""}
            {!c.reason && outcome.weight_source === "ai" && outcome.defaulted_chapters > 0 && (
              <span className="ml-2 rounded-full bg-warn-100 px-2 py-0.5 text-xs text-warn-700">
                default share
              </span>
            )}
          </li>
        ))}
      </ul>
    </details>
  );
}

/** The class's teaching plan (task 6.4): draft it, read the outcome, accept it,
 *  and edit any lesson. A draft is only proposed until the tutor accepts it. */
export default function TeachingPlanView({
  groupId,
  subjectId,
}: {
  groupId: number;
  subjectId: number;
}) {
  const queryClient = useQueryClient();
  const plan = useQuery({
    queryKey: ["plan", groupId],
    queryFn: () => getPlan(groupId),
    // Poll only while a draft job is queued or running.
    refetchInterval: (query) => (query.state.data?.draft?.drafting ? POLL_MS : false),
  });
  const chapters = useQuery({
    queryKey: ["chapters", subjectId],
    queryFn: () => listChapters(subjectId),
  });
  // "Today" is the tutor's effective day (their own zone, else the
  // organization's), as the record form reads it, not the browser's.
  const myZone = useMyTimezone();
  const org = useQuery({ queryKey: ["my-organization"], queryFn: myOrganization });
  const today = dayKeyIn(new Date(), myZone ?? org.data?.timezone ?? null);
  const [error, setError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [confirmingReplan, setConfirmingReplan] = useState(false);
  // Said when a cancelled lesson could not be rescheduled (AV-120).
  const [notice, setNotice] = useState<string | null>(null);

  const refresh = () => queryClient.invalidateQueries({ queryKey: ["plan", groupId] });
  const draft = useMutation({
    mutationFn: () => draftPlan(groupId),
    onMutate: () => setError(null),
    onSuccess: (overview) => queryClient.setQueryData(["plan", groupId], overview),
    onError: (err) => setError(friendlyError(err)),
  });
  const accept = useMutation({
    mutationFn: () => acceptPlan(groupId),
    onMutate: () => setError(null),
    onSuccess: (overview) => {
      queryClient.setQueryData(["plan", groupId], overview);
      // The home's plan-check list reads the accepted plan.
      queryClient.invalidateQueries({ queryKey: ["today"] });
      // Accepting is the onboarding finish line: the server's state decides
      // whether the home is still the setup flow.
      queryClient.invalidateQueries({ queryKey: ["onboarding"] });
      setConfirming(false);
    },
    onError: (err) => {
      setConfirming(false);
      setError(friendlyError(err));
    },
  });
  const replan = useMutation({
    mutationFn: () => replanPlan(groupId),
    onMutate: () => setError(null),
    onSuccess: (overview) => {
      queryClient.setQueryData(["plan", groupId], overview);
      setConfirmingReplan(false);
    },
    onError: (err) => {
      setConfirmingReplan(false);
      setError(friendlyError(err));
    },
  });
  const cancelSlot = useMutation({
    mutationFn: (slotId: number) => cancelPlanSlot(groupId, slotId),
    onMutate: () => {
      setError(null);
      setNotice(null);
    },
    onSuccess: (result) => {
      queryClient.setQueryData(["plan", groupId], result.plan);
      // The shift moved lessons the home and the next-lesson suggestion read.
      for (const key of [["today"], ["lesson-reminders"], ["next-lesson", groupId]]) {
        queryClient.invalidateQueries({ queryKey: key });
      }
      // Said in the polite region: the row's buttons are gone, so nothing else tells.
      setNotice(
        result.shifted
          ? "Lesson cancelled; later lessons moved."
          : (result.message ?? "Lesson cancelled."),
      );
    },
    onError: (err) => setError(friendlyError(err)),
  });
  const edit = useMutation({
    mutationFn: (v: { slotId: number; patch: SlotPatch; done: () => void }) =>
      editPlanSlot(groupId, v.slotId, v.patch),
    onMutate: () => setError(null),
    onSuccess: async (_saved, v) => {
      queryClient.invalidateQueries({ queryKey: ["today"] });
      // Focus goes back only once the list shows the lesson where it now is.
      await refresh();
      v.done();
    },
    onError: (err) => setError(friendlyError(err)),
  });

  if (plan.isLoading) return <SectionSkeleton rows={3} label="Loading the lesson plan" />;
  if (plan.isError || !plan.data) {
    return (
      <ErrorState
        title="The lesson plan didn't load"
        error={plan.error}
        onRetry={() => plan.refetch()}
      />
    );
  }

  const { draft: proposed, accepted } = plan.data;
  const chapterList = chapters.data ?? [];
  const chaptersReady = chapters.isSuccess;
  const drafting = Boolean(proposed?.drafting) || draft.isPending || replan.isPending;
  const proposedSlots = proposed?.slots ?? [];
  const canAccept =
    !!proposed && !drafting && proposed.outcome?.status === "drafted" && proposedSlots.length > 0;
  const onSave = (slotId: number, patch: SlotPatch, done: () => void) =>
    edit.mutate({ slotId, patch, done });

  // Any existing draft is replaced by a re-plan (its inputs and breaks too, not
  // only its slots), so it is confirmed whenever one exists.
  const startReplan = () => (proposed ? setConfirmingReplan(true) : replan.mutate());

  // The draft's own notes (ReflowNote is separate again) sit with the draft.
  const outcomeList = outcomeNotes(proposed?.outcome ?? null, !!proposed?.draft_job_failed);
  const behindMessage = plan.data.progress ? behindText(plan.data.progress) : null;
  const behind = behindMessage !== null;
  // The live plan's one notice region: an error, then a note from the last
  // action (AV-120), then the "behind" nudge.
  const message = error
    ? { tone: "bg-risk-100 text-risk-600", text: error }
    : notice
      ? { tone: "bg-brand-50 text-brand-700", text: notice }
      : behindMessage
        ? { tone: "bg-warn-100 text-warn-700", text: behindMessage }
        : null;

  const liveSection = (live: PlanInputs) => (
    <div className="mt-4">
      <h4 className="text-sm font-medium text-ink-900">Live plan</h4>
      <p className="text-sm text-ink-500">
        Exam on {humanDate(live.exam_date)}.
        {live.accepted_at ? ` Accepted ${localDate(live.accepted_at)}.` : ""} Edit any lesson at any
        time; it stays accepted.
      </p>
      <ReflowNote reflow={live.outcome?.reflow} />
      {(live.slots ?? []).length === 0 ? (
        <p className="mt-2 text-sm text-ink-500">This plan has no lessons.</p>
      ) : (
        <SlotList
          slots={live.slots ?? []}
          chapters={chapterList}
          chaptersReady={chaptersReady}
          chaptersError={chapters.isError}
          onRetryChapters={() => chapters.refetch()}
          saving={edit.isPending}
          onSave={onSave}
          onCancel={(slotId, done) => cancelSlot.mutate(slotId, { onSuccess: done })}
          cancellingId={cancelSlot.isPending ? (cancelSlot.variables ?? null) : null}
          cancelBusy={cancelSlot.isPending}
          today={today}
          version={queryClient.getQueryState(["plan", groupId])?.dataUpdateCount ?? 0}
        />
      )}
    </div>
  );

  return (
    <SectionCard>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="font-medium text-ink-900">Lesson plan</h3>
          <p className="mt-1 text-sm text-ink-500">
            Chapters laid across the calendar up to the exam. Nothing counts until you accept it.
          </p>
        </div>
        <Button
          variant={accepted ? "secondary" : "primary"}
          disabled={!proposed || drafting}
          loading={drafting}
          onClick={() => draft.mutate()}
        >
          {drafting ? "Drafting…" : accepted ? "Draft a new plan" : "Draft my plan"}
        </Button>
      </div>
      {!proposed && (
        <p className="mt-3 text-sm text-ink-500">
          Open Plan settings and save the plan inputs to draft a plan.
        </p>
      )}
      {/* Two always-mounted regions, so a change of text is announced: an
          error is an alert, any other note is polite. The text is the most
          important thing to say: an error, then a note from the last action,
          then the "behind" nudge. Re-plan sits outside both so it is not read
          again with each message, and stays whenever the plan is behind. */}
      <div className={`${message || behind ? "mt-3 " : ""}flex flex-wrap items-center gap-3`}>
        <div className="min-w-0 flex-1">
          <div role="alert">
            {error && (
              <p className="rounded-md bg-risk-100 px-3 py-2 text-sm text-risk-600">{error}</p>
            )}
          </div>
          <div role="status" aria-live="polite">
            {!error && message && (
              <p className={`rounded-md px-3 py-2 text-sm ${message.tone}`}>{message.text}</p>
            )}
          </div>
        </div>
        {behind && (
          <Button
            size="sm"
            variant="secondary"
            loading={replan.isPending || drafting}
            disabled={replan.isPending || drafting}
            onClick={startReplan}
          >
            Re-plan
          </Button>
        )}
      </div>

      {accepted && liveSection(accepted)}

      {proposed && (proposedSlots.length > 0 || proposed.outcome || proposed.draft_job_failed) && (
        <div className="mt-6 border-t border-line pt-4">
          <h4 className="text-sm font-medium text-ink-900">
            {accepted ? "Proposed changes" : "Draft plan"}
          </h4>
          {outcomeList.length > 0 && <OutcomeBanner notes={outcomeList} />}
          <ReflowNote reflow={proposed.outcome?.reflow} />
          {proposed.outcome && <Reasons outcome={proposed.outcome} />}
          {proposedSlots.length > 0 && (
            <SlotList
              slots={proposedSlots}
              chapters={chapterList}
              chaptersReady={chaptersReady}
              chaptersError={chapters.isError}
              onRetryChapters={() => chapters.refetch()}
              locked={drafting}
              saving={edit.isPending}
              onSave={onSave}
              today={today}
              version={queryClient.getQueryState(["plan", groupId])?.dataUpdateCount ?? 0}
            />
          )}
          <div className="mt-4 flex justify-end">
            <Button disabled={!canAccept} onClick={() => setConfirming(true)}>
              Accept plan
            </Button>
          </div>
        </div>
      )}

      <ConfirmDialog
        open={confirming}
        title="Accept this plan?"
        body={
          accepted
            ? "It replaces the live plan. You can still edit any lesson afterwards."
            : "It becomes the live plan. You can still edit any lesson afterwards."
        }
        confirmLabel="Accept plan"
        busy={accept.isPending}
        onConfirm={() => accept.mutate()}
        onCancel={() => setConfirming(false)}
      />
      <ConfirmDialog
        open={confirmingReplan}
        title="Re-plan from today?"
        body="This replaces the draft you have with a fresh one. Your live plan stays as it is until you accept the new draft."
        confirmLabel="Re-plan"
        busy={replan.isPending}
        onConfirm={() => replan.mutate()}
        onCancel={() => setConfirmingReplan(false)}
      />
    </SectionCard>
  );
}
