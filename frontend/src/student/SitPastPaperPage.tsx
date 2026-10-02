import { useState, type FormEvent } from "react";
import { useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Clock } from "lucide-react";
import { getPastPaper, logAttempt, myAttempt, pastPaperPaperPath } from "../api/pastPapers";
import { AuthFileLink } from "../components/AuthFile";
import { ApiError } from "../api/client";
import { Button, Field, FileInput, Input } from "../components/controls";
import { ErrorState, NotFoundState, PageHeader, PageSkeleton } from "../components/page";
import { SectionCard } from "../components/ui";
import { friendlyError } from "../lib/errors";

const BACK = { to: "/student/past-papers", label: "Past papers" };

/** "14 Sep 2026" for a `YYYY-MM-DD` the student typed. Formatted in UTC
    because it is a calendar date, not an instant — read in a zone west of
    Greenwich, midnight UTC would otherwise show as the day before. */
function formatAttemptDate(day: string): string {
  const at = new Date(`${day}T00:00:00Z`);
  if (Number.isNaN(at.getTime())) return day;
  return at.toLocaleDateString(undefined, {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  });
}

export default function SitPastPaperPage() {
  const { pastPaperId } = useParams();
  const id = Number(pastPaperId);
  const queryClient = useQueryClient();

  const paper = useQuery({ queryKey: ["past-paper", id], queryFn: () => getPastPaper(id) });
  const attempt = useQuery({
    queryKey: ["past-paper-attempt", id],
    queryFn: () => myAttempt(id),
    refetchInterval: (query) => (query.state.data?.status === "being_marked" ? 4000 : false),
  });

  const [files, setFiles] = useState<File[]>([]);
  const [attemptedAt, setAttemptedAt] = useState(() => new Date().toISOString().slice(0, 10));
  const [timed, setTimed] = useState(true);
  const [minutes, setMinutes] = useState("");
  const [error, setError] = useState<string | null>(null);

  const submit = useMutation({
    mutationFn: () =>
      logAttempt(id, {
        files,
        attempted_at: attemptedAt,
        timed,
        time_taken_minutes: minutes ? Number(minutes) : null,
      }),
    onSuccess: () => {
      setFiles([]);
      queryClient.invalidateQueries({ queryKey: ["past-paper-attempt", id] });
    },
    onError: (err) => setError(friendlyError(err, "Your answers couldn't be uploaded. Try again.")),
  });

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (files.length) submit.mutate();
  }

  if (paper.isLoading) return <PageSkeleton rows={3} label="Loading the past paper" />;
  if (paper.isError && paper.error instanceof ApiError && paper.error.status === 404) {
    return (
      <NotFoundState
        title="We couldn't find that past paper"
        body="It may have been removed, or the link may be wrong."
        back={{ to: BACK.to, label: "Back to past papers" }}
      />
    );
  }
  if (paper.isError || !paper.data) {
    return (
      <div className="max-w-2xl">
        <PageHeader title="Past paper" back={BACK} />
        <ErrorState
          title="Couldn't load this past paper."
          error={paper.error}
          onRetry={() => void paper.refetch()}
        />
      </div>
    );
  }
  const p = paper.data;
  const a = attempt.data;

  // "80 marks · 90 minutes allowed" — a missing value is left out, never 0.
  const facts = [
    p.total_marks ? `${p.total_marks} marks` : null,
    p.duration_minutes ? `${p.duration_minutes} minutes allowed` : null,
  ].filter(Boolean);

  return (
    <div className="max-w-2xl space-y-6">
      <PageHeader
        title={p.display_title}
        back={BACK}
        description={facts.length > 0 ? facts.join(" · ") : undefined}
        actions={<AuthFileLink path={pastPaperPaperPath(p.id)} label="Open the question paper" />}
      />

      {a?.status === "marked" ? (
        <SectionCard>
          <h2 className="flex items-center gap-2 font-display text-lg text-ink-900">
            <CheckCircle2 aria-hidden className="h-5 w-5 text-ok-700" />
            Your result
          </h2>
          {/* An absent total is words, never "null / null" or a zero (PROD-2). */}
          {a.raw_marks != null && a.max_marks != null ? (
            <p className="mt-2 text-ink-700">
              <span className="font-display text-2xl tabular-nums text-ink-900">{a.raw_marks}</span>{" "}
              out of <span className="tabular-nums">{a.max_marks}</span> marks
            </p>
          ) : (
            <p className="mt-2 text-sm text-ink-500">Your total isn&apos;t ready yet.</p>
          )}
          {/* Everything on this line is the student's own account — the
              platform did not observe the date, the conditions or the time
              taken — so it is labelled as theirs (PROD-8, UX-20). */}
          <p className="mt-2 text-sm text-ink-500">
            As you logged it: {a.attempted_at ? `sat ${formatAttemptDate(a.attempted_at)}, ` : ""}
            {a.timed ? "under timed conditions" : "untimed"}
            {a.time_taken_minutes ? `, took ${a.time_taken_minutes} minutes` : ""}.
          </p>
          <p className="mt-3 text-sm text-ink-500">
            Your per-question marks and feedback are in your progress.
          </p>
        </SectionCard>
      ) : a?.status === "being_marked" ? (
        <div
          aria-live="polite"
          className="flex gap-3 rounded-xl border border-line bg-warn-100 p-4 text-sm text-warn-700"
        >
          <Clock aria-hidden className="mt-0.5 h-4 w-4 shrink-0" />
          <p>Your answers are being marked. This page checks for your result automatically.</p>
        </div>
      ) : (
        <SectionCard>
          <form onSubmit={onSubmit} className="space-y-5">
            <div>
              <h2 className="font-display text-lg text-ink-900">Log your attempt</h2>
              <p className="mt-0.5 text-sm text-ink-500">
                Sit the paper, then upload clear photos or a scan of every page of your answers, in
                order.
              </p>
            </div>
            <Field label="Your answers">
              <FileInput
                multiple
                accept="application/pdf,image/*"
                onFiles={setFiles}
                prompt="Choose photos or a PDF"
                hint="JPG, PNG or PDF — add every page, in order"
              />
            </Field>

            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="When did you sit it?">
                <Input
                  type="date"
                  value={attemptedAt}
                  onChange={(e) => setAttemptedAt(e.target.value)}
                />
              </Field>
              <Field label="How long did it take? (minutes)" optional>
                <Input
                  type="number"
                  min={1}
                  inputMode="numeric"
                  value={minutes}
                  onChange={(e) => setMinutes(e.target.value)}
                />
              </Field>
            </div>

            <div>
              <label className="flex items-center gap-2 text-sm text-ink-900">
                <input
                  type="checkbox"
                  checked={timed}
                  onChange={(e) => setTimed(e.target.checked)}
                  className="h-4 w-4 accent-brand-600"
                />
                I sat this under timed exam conditions
              </label>
              <p className="mt-1.5 text-xs text-ink-500">
                We take your word for this — be honest, it changes what your readiness score means.
              </p>
            </div>

            {error && (
              <p role="alert" className="text-sm text-risk-600">
                {error}
              </p>
            )}
            <Button type="submit" loading={submit.isPending} disabled={files.length === 0}>
              Submit for marking
            </Button>
          </form>
        </SectionCard>
      )}
    </div>
  );
}
