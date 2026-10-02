import { useEffect, useState, type FormEvent } from "react";
import { useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, Timer } from "lucide-react";
import { getMock, mockPaperPath, myMockSubmission, openMock, sitMock } from "../api/mocks";
import { AuthFileLink } from "../components/AuthFile";
import { ApiError } from "../api/client";
import { Button, Field, FileInput, Textarea } from "../components/controls";
import { ErrorState, NotFoundState, PageHeader, PageSkeleton } from "../components/page";
import { SectionCard } from "../components/ui";
import { friendlyError } from "../lib/errors";

const BACK = { to: "/student/mocks", label: "Mocks" };

/** How often the page re-asks the server how long is left.
 *
 *  The number that matters. Between two answers the page counts down off the
 *  device clock, which a paused tab, a slept laptop or a hand-set clock can all
 *  get wrong — so the window in which a display can drift from the truth is
 *  capped at this. The local tick is a display; the server is the limit
 *  (`AV-116`). */
const CLOCK_REFETCH_MS = 30_000;

function formatLeft(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  const pad = (n: number) => String(n).padStart(2, "0");
  return h > 0 ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`;
}

export default function SitMockPage() {
  const { mockId } = useParams();
  const id = Number(mockId);
  const queryClient = useQueryClient();

  const mock = useQuery({ queryKey: ["mock", id], queryFn: () => getMock(id) });
  const submission = useQuery({
    queryKey: ["my-mock-submission", id],
    queryFn: () => myMockSubmission(id),
  });

  // This POST is what starts the clock, so it must fire once — not once per
  // render. A query keyed on the mock does that: React Query dedupes it, and
  // the server is idempotent if a refetch (the interval, or a refocused tab)
  // asks again, which is the point — every answer is the same running clock.
  const clock = useQuery({
    queryKey: ["mock-clock", id],
    queryFn: () => openMock(id),
    refetchInterval: CLOCK_REFETCH_MS,
    // Both deliberate. React Query stops interval refetches for a hidden tab
    // by default, and a student who switches away for twenty minutes would
    // come back to a local countdown that had drifted — the exact thing the
    // server clock exists to overrule. `"always"` on focus because the answer
    // is time-sensitive by nature: it is never "still fresh".
    refetchIntervalInBackground: true,
    refetchOnWindowFocus: "always",
  });

  // A once-a-second heartbeat, and nothing else. Server data stays in the
  // query cache rather than being copied into state (`FE-6`); this is the tick
  // that makes the countdown move between server answers.
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);

  const [files, setFiles] = useState<File[]>([]);
  // Remounts the picker after a hand-in so it stops listing files already sent.
  const [pickerKey, setPickerKey] = useState(0);
  const [typed, setTyped] = useState("");
  const [error, setError] = useState<string | null>(null);

  const submit = useMutation({
    mutationFn: () => sitMock(id, files, typed),
    onSuccess: () => {
      setFiles([]);
      setPickerKey((k) => k + 1);
      setTyped("");
      queryClient.invalidateQueries({ queryKey: ["my-mock-submission", id] });
    },
    onError: (err) =>
      setError(friendlyError(err, "Your answers couldn't be handed in. Try again.")),
  });

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (files.length || typed.trim()) submit.mutate();
  }

  if (mock.isLoading) return <PageSkeleton rows={3} label="Loading your mock" />;
  if (mock.isError && mock.error instanceof ApiError && mock.error.status === 404) {
    return (
      <NotFoundState
        title="We couldn't find that mock"
        body="It may have been removed by your tutor, or the link may be wrong."
        back={{ to: BACK.to, label: "Back to mocks" }}
      />
    );
  }
  if (mock.isError || !mock.data) {
    return (
      <div className="max-w-2xl">
        <PageHeader title="Mock" back={BACK} />
        <ErrorState
          title="Couldn't load this mock."
          error={mock.error}
          onRetry={() => void mock.refetch()}
        />
      </div>
    );
  }
  const m = mock.data;
  const sub = submission.data;

  // `null` when the tutor set no duration. There is then no countdown to show —
  // not "0:00", not an empty bar (`PROD-2`, `UX-19`).
  const serverSeconds = clock.data?.seconds_remaining ?? null;
  const secondsLeft =
    serverSeconds === null
      ? null
      : Math.min(
          serverSeconds,
          Math.max(0, serverSeconds - Math.floor((now - clock.dataUpdatedAt) / 1000)),
        );
  const timeUp = clock.data?.overdue === true || secondsLeft === 0;

  // What the paper is, in words: "80 marks · 90 minutes allowed". A missing
  // value is left out rather than shown as 0 (PROD-2).
  const facts = [
    m.total_marks ? `${m.total_marks} marks` : null,
    m.duration_minutes ? `${m.duration_minutes} minutes allowed` : null,
  ].filter(Boolean);

  return (
    <div className="max-w-2xl space-y-6">
      <PageHeader
        title={m.title}
        back={BACK}
        description={facts.length > 0 ? facts.join(" · ") : undefined}
        actions={<AuthFileLink path={mockPaperPath(m.id)} label="Open the question paper" />}
      />

      {timeUp && (
        <div
          role="status"
          className="flex gap-3 rounded-xl border border-line bg-warn-100 p-4 text-sm text-warn-700"
        >
          <AlertTriangle aria-hidden className="mt-0.5 h-4 w-4 shrink-0" />
          <p>Your time is up. You can still hand in — your tutor will see it came in late.</p>
        </div>
      )}
      {/* Not an `else`: a mock with no duration set has no countdown to show
          either way, so both branches are absent rather than one standing in
          for the other (`PROD-2`, `UX-19`). */}
      {!timeUp && secondsLeft !== null && (
        <SectionCard className="flex items-center gap-4">
          <span className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-brand-50 text-brand-600">
            <Timer aria-hidden className="h-5 w-5" />
          </span>
          <div>
            <div className="text-sm text-ink-500">Time left</div>
            <div className="font-display text-2xl tabular-nums text-ink-900">
              {formatLeft(secondsLeft)}
            </div>
            <p className="mt-0.5 text-xs text-ink-500">
              Timed on our servers, so closing this page doesn&apos;t buy you more time.
            </p>
          </div>
        </SectionCard>
      )}

      {sub ? (
        <SectionCard>
          <h2 className="flex items-center gap-2 font-display text-lg text-ink-900">
            <CheckCircle2 aria-hidden className="h-5 w-5 text-ok-700" />
            Handed in
          </h2>
          {/* Measured by us from the clock, so it is stated plainly — unlike a
              past paper's self-declared minutes, which carry a caveat
              (`PROD-8`, `UX-20`). Absent stays absent (`PROD-2`). */}
          {sub.measured_minutes !== null && sub.measured_minutes !== undefined && (
            <p className="mt-2 text-sm text-ink-700">You took {sub.measured_minutes} minutes.</p>
          )}
          {sub.submitted_late && (
            <p className="mt-2 text-sm text-warn-700">
              This came in after your time was up, so it's flagged for your tutor. It is still
              marked in full.
            </p>
          )}
          <p className="mt-3 text-sm text-ink-500">
            Your per-question marks and feedback appear in your progress once it has been marked.
          </p>
        </SectionCard>
      ) : (
        <SectionCard>
          <form onSubmit={onSubmit} className="space-y-5">
            <div>
              <h2 className="font-display text-lg text-ink-900">Hand in your answers</h2>
              <p className="mt-0.5 text-sm text-ink-500">
                Upload clear photos or a scan of every page of your answers, in order — or type them
                below.
              </p>
            </div>
            <Field label="Photos or a scan of your answers">
              <FileInput
                key={pickerKey}
                multiple
                accept="application/pdf,image/*"
                onFiles={setFiles}
                prompt="Choose photos or a PDF"
                hint="JPG, PNG or PDF — add every page, in order"
              />
            </Field>

            <Field label="Or type your answers">
              <Textarea value={typed} onChange={(e) => setTyped(e.target.value)} rows={6} />
            </Field>

            {error && (
              <p role="alert" className="text-sm text-risk-600">
                {error}
              </p>
            )}
            {clock.isPending && <p className="text-sm text-ink-500">Starting your clock…</p>}
            {clock.isError && (
              <p className="text-sm text-warn-700">
                We couldn&apos;t start your clock, so this hand-in won&apos;t be timed. You can
                still hand in — your tutor will see it wasn&apos;t timed.
              </p>
            )}
            {/* Disabled while the clock is still starting, never because it has
                run out. Handing in before `/open` has answered would record no
                start time at all — the submission cannot then be timed or flagged
                — but a *failed* open must not block the work: losing a student's
                answers is worse than losing the measurement. And a late hand-in
                is accepted in full and flagged, which is the point of `AV-116`. */}
            <Button
              type="submit"
              loading={submit.isPending}
              disabled={
                clock.isPending ||
                submission.isPending ||
                (files.length === 0 && typed.trim() === "")
              }
            >
              Hand in
            </Button>
          </form>
        </SectionCard>
      )}
    </div>
  );
}
