import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  acceptPlan,
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
import { listChapters, type Chapter } from "../api/syllabus";
import { friendlyError } from "../lib/errors";
import { shortDay } from "../lib/planDates";
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
  return [...weeks.entries()];
}

/** Says plainly when the weights did not come from the AI, and why (`PROD-1`). */
function OutcomeBanner({
  outcome,
  jobFailed,
}: {
  outcome: DraftOutcome | null;
  jobFailed: boolean;
}) {
  const notes: { tone: "risk" | "warn"; text: string }[] = [];
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
  if (notes.length === 0) return null;
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
 *  blame. Offers a re-plan that only drafts; the tutor still accepts it. */
function BehindBanner({
  progress,
  busy,
  onReplan,
}: {
  progress: PlanProgress;
  busy: boolean;
  onReplan: () => void;
}) {
  if (progress.missed < 1 || !progress.earliest_missed_date) return null;
  const n = progress.missed;
  return (
    <div
      role="status"
      className="mt-3 flex flex-wrap items-center justify-between gap-3 rounded-md bg-warn-100 px-3 py-2 text-sm text-warn-700"
    >
      <span>
        {n} planned {n === 1 ? "lesson hasn't" : "lessons haven't"} been recorded since{" "}
        {shortDay(progress.earliest_missed_date)} — record {n === 1 ? "it" : "them"}, or re-plan
        from today.
      </span>
      <Button size="sm" variant="secondary" loading={busy} disabled={busy} onClick={onReplan}>
        Re-plan
      </Button>
    </div>
  );
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
  onSave: (patch: { scheduled_date?: string; chapter_id?: number }, done: () => void) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [date, setDate] = useState(slot.scheduled_date);
  const [chapterId, setChapterId] = useState(slot.chapter_id);

  if (editing) {
    const changed = date !== slot.scheduled_date || chapterId !== slot.chapter_id;
    return (
      <li className="flex flex-wrap items-end gap-3 px-3 py-2">
        <label className="text-sm text-ink-700">
          <span className="block text-xs text-ink-500">Date</span>
          <Input
            type="date"
            aria-label="Lesson date"
            value={date}
            onChange={(e) => setDate(e.target.value)}
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
              },
              () => setEditing(false),
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
            setEditing(false);
          }}
        >
          Cancel
        </Button>
      </li>
    );
  }
  return (
    <li className="flex items-center justify-between gap-3 px-3 py-2">
      <span className="min-w-0 text-sm text-ink-700">
        <span className="tabular-nums text-ink-500">{humanDate(slot.scheduled_date)}</span>{" "}
        <span className="font-medium text-ink-900">
          {slot.chapter_code} {slot.chapter_title}
        </span>
        {slot.provenance === "manually_modified" && (
          <span className="ml-2 rounded-full bg-brand-50 px-2 py-0.5 text-xs text-brand-700">
            hand-edited
          </span>
        )}
        {(slot.provenance === "confirmed" || slot.provenance === "completed") && (
          <span className="ml-2 rounded-full bg-ok-100 px-2 py-0.5 text-xs text-ok-700">
            taught
          </span>
        )}
      </span>
      <Button
        size="sm"
        variant="ghost"
        aria-label={`Edit the ${humanDate(slot.scheduled_date)} lesson`}
        disabled={locked}
        onClick={() => setEditing(true)}
      >
        Edit
      </Button>
    </li>
  );
}

function SlotList({
  slots,
  chapters,
  chaptersReady,
  chaptersError,
  onRetryChapters,
  locked = false,
  saving,
  onSave,
}: {
  slots: PlanSlot[];
  chapters: Chapter[];
  chaptersReady: boolean;
  chaptersError: boolean;
  onRetryChapters: () => void;
  locked?: boolean;
  saving: boolean;
  onSave: (
    slotId: number,
    patch: { scheduled_date?: string; chapter_id?: number },
    done: () => void,
  ) => void;
}) {
  return (
    <div className="mt-3 space-y-4">
      {groupByWeek(slots).map(([week, rows]) => (
        <div key={week}>
          <h5 className="text-xs font-medium uppercase tracking-wide text-ink-500">
            Week of {humanDate(week)}
          </h5>
          <ul className="mt-1 divide-y divide-line rounded-lg border border-line">
            {rows.map((slot) => (
              <SlotRow
                key={`${slot.id}-${slot.scheduled_date}-${slot.chapter_id}`}
                slot={slot}
                chapters={chapters}
                chaptersReady={chaptersReady}
                chaptersError={chaptersError}
                onRetryChapters={onRetryChapters}
                locked={locked}
                saving={saving}
                onSave={(patch, done) => onSave(slot.id, patch, done)}
              />
            ))}
          </ul>
        </div>
      ))}
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
  const [error, setError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [confirmingReplan, setConfirmingReplan] = useState(false);

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
  const edit = useMutation({
    mutationFn: (v: {
      slotId: number;
      patch: { scheduled_date?: string; chapter_id?: number };
      done: () => void;
    }) => editPlanSlot(groupId, v.slotId, v.patch),
    onMutate: () => setError(null),
    onSuccess: (_saved, v) => {
      v.done();
      queryClient.invalidateQueries({ queryKey: ["today"] });
      return refresh();
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
  const onSave = (
    slotId: number,
    patch: { scheduled_date?: string; chapter_id?: number },
    done: () => void,
  ) => edit.mutate({ slotId, patch, done });

  // Any existing draft is replaced by a re-plan (its inputs and breaks too, not
  // only its slots), so it is confirmed whenever one exists.
  const startReplan = () => (proposed ? setConfirmingReplan(true) : replan.mutate());

  const liveSection = (live: PlanInputs) => (
    <div className="mt-4">
      <h4 className="text-sm font-medium text-ink-900">Live plan</h4>
      <p className="text-sm text-ink-500">
        Exam on {humanDate(live.exam_date)}.
        {live.accepted_at ? ` Accepted ${localDate(live.accepted_at)}.` : ""} Edit any lesson at any
        time; it stays accepted.
      </p>
      {plan.data.progress && (
        <BehindBanner
          progress={plan.data.progress}
          busy={replan.isPending || drafting}
          onReplan={startReplan}
        />
      )}
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
        <p className="mt-3 text-sm text-ink-500">Save the plan inputs above to draft a plan.</p>
      )}
      {error && (
        <p role="alert" className="mt-3 rounded-md bg-risk-100 px-3 py-2 text-sm text-risk-600">
          {error}
        </p>
      )}

      {accepted && liveSection(accepted)}

      {proposed && (proposedSlots.length > 0 || proposed.outcome || proposed.draft_job_failed) && (
        <div className="mt-6 border-t border-line pt-4">
          <h4 className="text-sm font-medium text-ink-900">
            {accepted ? "Proposed changes" : "Draft plan"}
          </h4>
          <ReflowNote reflow={proposed.outcome?.reflow} />
          <OutcomeBanner
            outcome={proposed.outcome ?? null}
            jobFailed={!!proposed.draft_job_failed}
          />
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
