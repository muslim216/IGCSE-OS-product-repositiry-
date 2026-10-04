import { useEffect, useId, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ExternalLink, FileText } from "lucide-react";
import { mistakeSourceLabel } from "./mistakeSourceLabel";
import {
  fetchFileUrl,
  finalizeSubmission,
  getSubmission,
  markHistory,
  reviewQueue,
  reviseMistake,
  saveMarks,
  submissionFilePath,
  type MarkRow,
  type MistakeRow,
  type SubmissionDetail,
  type SubmissionFileInfo,
} from "../api/homework";
import { getMistakeCategories, type MistakeCategoryItem } from "../api/mistakeCategories";
import { ApiError } from "../api/client";
import { friendlyError } from "../lib/errors";
import { Reveal, SectionCard } from "../components/ui";
import { Button, Textarea, inputClasses } from "../components/controls";
import { ErrorState, NotFoundState, PageHeader, PageSkeleton, Skeleton } from "../components/page";

interface Draft {
  final_marks: number | null;
  final_feedback: string;
}

const CONFIDENCE_STYLE: Record<string, string> = {
  high: "bg-ok-100 text-ok-700",
  medium: "bg-ok-100 text-ok-700",
  low: "bg-warn-100 text-warn-700",
  unsure: "bg-surface-muted text-ink-500",
  tutor_only: "bg-surface-muted text-ink-500",
};

const CONFIDENCE_LABEL: Record<string, string> = {
  high: "AI confident",
  medium: "AI confident",
  low: "AI unsure — hard to read",
  unsure: "No mark scheme — your call",
  tutor_only: "No mark scheme — your call",
};

/** The submission's state, as the header badge says it. */
const STATUS_BADGE: Record<string, { label: string; classes: string }> = {
  submitted: { label: "Waiting to be marked", classes: "bg-surface-muted text-ink-700" },
  marking: { label: "Being marked", classes: "bg-surface-muted text-ink-700" },
  ai_marked: { label: "AI draft ready", classes: "bg-warn-100 text-warn-700" },
  ai_failed: { label: "AI couldn't mark this", classes: "bg-risk-100 text-risk-600" },
  needs_review: { label: "Needs your review", classes: "bg-warn-100 text-warn-700" },
  auto_finalized: { label: "Marked automatically", classes: "bg-ok-100 text-ok-700" },
  finalized: { label: "Finalized", classes: "bg-ok-100 text-ok-700" },
};

/**
 * One uploaded page of the student's work, fetched with the tutor's token.
 *
 * An image renders inline so the tutor marks with the work in view. A PDF
 * cannot: the CSP allows `blob:` for images only (no frame or object source),
 * so it gets a clear button that opens it in a new tab instead of a link that
 * reads like a file name.
 */
function WorkFile({
  path,
  file,
  label,
}: {
  path: string;
  file: SubmissionFileInfo;
  label: string;
}) {
  const isPdf = file.mime === "application/pdf";
  const [attempt, setAttempt] = useState(0);
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const [opening, setOpening] = useState(false);

  useEffect(() => {
    if (isPdf) return;
    let created: string | null = null;
    let cancelled = false;
    fetchFileUrl(path)
      .then((u) => {
        if (cancelled) {
          URL.revokeObjectURL(u);
          return;
        }
        created = u;
        setUrl(u);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
      if (created) URL.revokeObjectURL(created);
    };
  }, [path, isPdf, attempt]);

  async function openPdf() {
    setOpening(true);
    setFailed(false);
    try {
      window.open(await fetchFileUrl(path), "_blank");
    } catch {
      // Tutor material can redirect to the object store since task 1.2, so a
      // network or bucket CORS failure lands here rather than as a status.
      setFailed(true);
    } finally {
      setOpening(false);
    }
  }

  if (isPdf) {
    return (
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-line bg-surface p-4">
        <span className="flex min-w-0 items-center gap-3">
          <FileText aria-hidden className="h-5 w-5 shrink-0 text-brand-600" />
          <span className="min-w-0">
            <span className="block truncate text-sm font-medium text-ink-900">{file.name}</span>
            <span className="block text-xs text-ink-500">
              {failed ? "That didn't open. Try again." : `${label} · PDF, opens in a new tab`}
            </span>
          </span>
        </span>
        <Button variant="secondary" size="sm" loading={opening} onClick={openPdf}>
          <ExternalLink aria-hidden className="h-4 w-4" />
          Open PDF
        </Button>
      </div>
    );
  }

  return (
    <figure className="overflow-hidden rounded-xl border border-line bg-surface">
      {url ? (
        <img src={url} alt={`${label} of the student's work`} className="block w-full" />
      ) : failed ? (
        <div role="alert" className="flex flex-col items-center gap-3 px-4 py-10 text-center">
          <p className="text-sm text-ink-500">This page didn't load.</p>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => {
              setFailed(false);
              setAttempt((n) => n + 1);
            }}
          >
            Try again
          </Button>
        </div>
      ) : (
        <Skeleton className="h-72 w-full" />
      )}
      <figcaption className="flex items-center justify-between gap-3 border-t border-line px-3 py-2 text-xs text-ink-500">
        <span className="truncate">
          {label} · {file.name}
        </span>
        {url && (
          <a
            href={url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex shrink-0 items-center gap-1 font-medium text-brand-600 hover:text-brand-700"
          >
            Full size
            <ExternalLink aria-hidden className="h-3 w-3" />
          </a>
        )}
      </figcaption>
    </figure>
  );
}

export default function SubmissionReviewPage() {
  const { submissionId } = useParams();
  const id = Number(submissionId);
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [params] = useSearchParams();

  // Traversal is opt-in via ?queue=review, so arriving from an assignment page
  // or a bookmark still behaves exactly as it did — the queue controls only
  // appear when the tutor actually came from the queue.
  const inQueue = params.get("queue") === "review";

  const submission = useQuery({
    queryKey: ["submission", id],
    queryFn: () => getSubmission(id),
  });

  const queue = useQuery({
    queryKey: ["review-queue"],
    queryFn: reviewQueue,
    enabled: inQueue,
    // The queue is the traversal order for this sitting: refetching mid-review
    // would renumber "1 of 6" under the tutor as items leave it.
    staleTime: Infinity,
  });

  /* The tutor's own words for what went wrong (4.1), for the revision picker.
     Only saved categories: a `source === "none"` reply is a published starting
     point nobody has confirmed, and offering one here would write a category
     the tutor never chose (PROD-8). */
  const subjectId = submission.data?.subject_id;
  const categories = useQuery({
    queryKey: ["mistake-categories", subjectId],
    queryFn: () => getMistakeCategories(subjectId!),
    enabled: subjectId !== undefined,
  });
  /* Three different facts, and an empty list cannot tell them apart: the
     query is still running, it failed, or the tutor genuinely has none saved.
     Rendered as one they all read as "you have not set these up", which is a
     false statement about the tutor's own configuration on two of the three
     (PROD-2 applied to a control rather than a metric) — and it is what makes
     a live category render as "(archived)" for the length of a round trip. */
  const liveCategories: MistakeCategoryItem[] =
    categories.data?.source === "organization" ? categories.data.categories : [];
  const categoryState = categories.isPending
    ? "loading"
    : categories.isError
      ? "error"
      : liveCategories.length > 0
        ? "ready"
        : "none";

  const queueItems = queue.data ?? [];
  const position = queueItems.findIndex((item) => item.submission_id === id);
  const next = position >= 0 ? queueItems[position + 1] : undefined;

  const goNext = () => {
    if (next) navigate(`/tutor/submissions/${next.submission_id}?queue=review`);
    else navigate("/tutor/review");
  };

  const [drafts, setDrafts] = useState<Record<number, Draft>>({});
  const [error, setError] = useState<string | null>(null);

  /* Seeded once per submission, not on every change to `submission.data`.
     This used to re-seed — and so discard every unsaved edit — whenever that
     query refetched, which was harmless while the only thing that invalidated
     it was an explicit save. Retagging a mistake (4.3) invalidates it too, so
     a tutor half-way through typing marks on question 4 who corrected the
     AI's tag on question 1 would silently lose the typing. Keyed on the id
     rather than dropped, because this component stays mounted while the
     review queue walks it from one submission to the next — and the keys are
     question ids, which would otherwise carry one student's marks onto
     another's. */
  const seededFor = useRef<number | null>(null);
  useEffect(() => {
    if (!submission.data || seededFor.current === submission.data.id) return;
    seededFor.current = submission.data.id;
    const next: Record<number, Draft> = {};
    for (const m of submission.data.marks) {
      // Seed the tutor's editable value from any saved final, else the AI proposal.
      next[m.question_id] = {
        final_marks: m.final_marks ?? m.ai_marks,
        final_feedback: m.final_feedback ?? m.ai_feedback ?? "",
      };
    }
    setDrafts(next);
  }, [submission.data]);

  const finalized = submission.data?.status === "finalized";
  const reviewCount =
    submission.data?.marks.filter((m) => m.needs_review || m.remark_requested).length ?? 0;

  const save = useMutation({
    mutationFn: () =>
      saveMarks(
        id,
        Object.entries(drafts).map(([qid, d]) => ({
          question_id: Number(qid),
          final_marks: d.final_marks,
          final_feedback: d.final_feedback || null,
        })),
      ),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["submission", id] }),
    onError: (err) => setError(friendlyError(err)),
  });

  /* Finalizing always saves first, and that save is what writes the append-only
     MarkOverrideAudit row for any mark the tutor changed (PROD-7, AI-12).
     "Finalize & next" reuses this same mutation rather than taking a shortcut to
     the finalize endpoint — a faster path that skipped the save would silently
     drop both the tutor's edits and the audit trail of them. */
  const finalize = useMutation({
    mutationFn: async (advance: boolean) => {
      await saveMarks(
        id,
        Object.entries(drafts).map(([qid, d]) => ({
          question_id: Number(qid),
          final_marks: d.final_marks,
          final_feedback: d.final_feedback || null,
        })),
      );
      await finalizeSubmission(id);
      return advance;
    },
    onSuccess: (advance) => {
      queryClient.invalidateQueries({ queryKey: ["submission", id] });
      if (advance) goNext();
    },
    onError: (err) => setError(friendlyError(err)),
  });

  /* An unmarked question contributes nothing to either side of the total, and
     the count of them is shown beside it. Adding its max to the denominator
     while its blank mark counted 0 in the numerator — which is what `?? 0` did
     — showed the tutor a total the student had not scored, and it fell as they
     worked rather than climbing (PROD-2, UX-19). */
  const totals = useMemo(() => {
    if (!submission.data) return { got: 0, max: 0, unmarked: 0 };
    let got = 0;
    let max = 0;
    let unmarked = 0;
    for (const m of submission.data.marks) {
      const marks = drafts[m.question_id]?.final_marks;
      if (marks === null || marks === undefined) {
        unmarked += 1;
        continue;
      }
      got += marks;
      max += m.max_marks;
    }
    return { got, max, unmarked };
  }, [submission.data, drafts]);

  if (submission.isLoading) return <PageSkeleton label="Loading the submission" />;
  if (
    submission.isError &&
    submission.error instanceof ApiError &&
    submission.error.status === 404
  ) {
    return (
      <NotFoundState
        title="We couldn't find that submission"
        body="It may have been removed, or the link may be wrong."
        back={{ to: "/tutor/review", label: "Review queue" }}
      />
    );
  }
  if (submission.isError || !submission.data) {
    return (
      <ErrorState
        title="This submission didn't load"
        error={submission.error}
        onRetry={() => submission.refetch()}
      />
    );
  }
  const s = submission.data;
  const status = STATUS_BADGE[s.status];

  /* In a queue the way back returns to the queue, not the assignment: six
     submissions used to cost six round trips back out through their parent
     assignment to find the next one. All three arms outside it, not two: a
     mock carries `mock_id`, never `assignment_id`, and an
     `assignment_id ? … : past-papers` test sent every mock to the past-papers
     library (API-20, one layer up). */
  const back = inQueue
    ? { to: "/tutor/review", label: "Review queue" }
    : s.assignment_id
      ? { to: `/tutor/assignments/${s.assignment_id}`, label: s.assignment_title }
      : s.mock_id
        ? { to: "/tutor/mocks", label: "Mocks" }
        : { to: "/tutor/past-papers", label: "Past papers" };

  return (
    <div>
      <PageHeader
        title={`${s.student_name}'s work`}
        back={back}
        description={s.assignment_title}
        meta={
          <>
            {status && (
              <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${status.classes}`}>
                {status.label}
              </span>
            )}
            <span className="text-ink-700">
              Total{" "}
              <span className="font-medium tabular-nums text-ink-900">
                {totals.got}/{totals.max}
              </span>
              {totals.unmarked > 0 && (
                <span className="ml-1.5 text-ink-500">({totals.unmarked} not marked yet)</span>
              )}
            </span>
            {inQueue && position >= 0 && (
              <span className="text-ink-500">
                Reviewing {position + 1} of {queueItems.length}
              </span>
            )}
          </>
        }
        actions={
          finalized ? (
            inQueue && (
              <Button variant="secondary" onClick={goNext}>
                {next ? "Next →" : "Back to queue"}
              </Button>
            )
          ) : (
            <>
              {inQueue && (
                // Skip leaves the marks exactly as they are — it is "not now",
                // never a decision, so it must not write anything.
                <Button variant="ghost" onClick={goNext}>
                  Skip
                </Button>
              )}
              <Button variant="secondary" loading={save.isPending} onClick={() => save.mutate()}>
                Save draft
              </Button>
              <Button loading={finalize.isPending} onClick={() => finalize.mutate(inQueue)}>
                {inQueue ? (next ? "Finalize & next" : "Finalize & finish") : "Finalize marks"}
              </Button>
            </>
          )
        }
      />

      {/* Notices sit between the header and the work, and take no space when
          there are none. */}
      <div className="mb-6 space-y-4 empty:hidden">
        {/* A zero here is not a finding — render nothing at all (UX-19). */}
        {s.bare_question_count > 0 && (
          <div className="rounded-xl border border-line bg-surface-muted px-4 py-3 text-sm text-ink-700">
            {s.bare_question_count === 1
              ? "1 question isn't linked to a syllabus topic."
              : `${s.bare_question_count} questions aren't linked to a syllabus topic.`}{" "}
            {/* All three arms, not two. A mock carries `mock_id`, never
                `assignment_id`, so an `assignment_id ? … : past-papers` test sends
                every mock to the past-papers library — the same silent narrowing
                to two arms that `API-20` exists to stop, one layer up. */}
            <Link
              to={
                s.assignment_id
                  ? `/tutor/assignments/${s.assignment_id}`
                  : s.mock_id
                    ? "/tutor/mocks"
                    : "/tutor/past-papers"
              }
              className="font-medium text-brand-600 hover:text-brand-700"
            >
              Fix this
            </Link>
          </div>
        )}

        {s.ai_error && (
          <div className="rounded-xl border border-line bg-warn-100 px-4 py-3 text-sm text-ink-900">
            <p>
              <span className="font-medium">The AI couldn't mark this work.</span> Mark each
              question yourself below.
            </p>
            {/* The job's own reason, folded away for whoever has to fix it —
                a raw exception string is not a message for a tutor. */}
            <details className="mt-2 text-xs text-ink-500">
              <summary className="cursor-pointer">Technical details</summary>
              <p className="mt-1 break-words font-mono">{s.ai_error}</p>
            </details>
          </div>
        )}
        {error && (
          <p role="alert" className="rounded-md bg-risk-100 px-3 py-2 text-sm text-risk-600">
            {error}
          </p>
        )}
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        {/* Left: the student's work. Sticky on wide screens, so the page being
            marked stays in view while the tutor works down the questions —
            and scrollable on its own, or a multi-page upload taller than the
            window would hide its later pages until the marks ran out. */}
        <section
          aria-labelledby="student-work"
          className="space-y-3 lg:sticky lg:top-6 lg:max-h-[calc(100vh-3rem)] lg:self-start lg:overflow-y-auto lg:pr-1"
        >
          <h2 id="student-work" className="text-lg text-ink-900">
            The student's work
          </h2>
          {s.typed_answer && (
            <SectionCard>
              {s.typed_answer.flag_reason && (
                // AV-93's scan fired. Every mark here is waiting on the tutor
                // regardless of how confident the AI was, so say why — a queue
                // with no explanation trains people to clear it.
                <p className="mb-3 rounded-md border border-warn-700 bg-warn-100 p-2 text-sm text-ink-900">
                  <span className="font-medium">
                    This typed answer contains text addressed to the marker.
                  </span>{" "}
                  Nothing here was marked automatically. Matched: {s.typed_answer.flag_reason}
                </p>
              )}
              <h3 className="text-sm font-medium text-ink-700">What the student typed</h3>
              <pre className="mt-2 max-h-96 overflow-auto whitespace-pre-wrap font-sans text-sm text-ink-900">
                {s.typed_answer.text}
              </pre>
            </SectionCard>
          )}
          {s.files.map((f, i) => (
            <WorkFile
              key={f.id}
              path={submissionFilePath(s.id, f.id)}
              file={f}
              label={s.files.length > 1 ? `Page ${i + 1} of ${s.files.length}` : "Upload"}
            />
          ))}
          {s.files.length === 0 && !s.typed_answer && (
            <p className="rounded-xl border border-line bg-surface px-4 py-6 text-center text-sm text-ink-500">
              No pages were uploaded with this submission.
            </p>
          )}
        </section>

        {/* Right: AI reading + tutor's editable marks, question by question */}
        <section aria-labelledby="marks-heading" className="space-y-3">
          <h2 id="marks-heading" className="text-lg text-ink-900">
            Marks
          </h2>
          <p className="text-sm text-ink-500">
            {reviewCount > 0
              ? `${reviewCount} of ${s.marks.length} marks need your decision`
              : "Every mark was made confidently — nothing needs your decision"}
          </p>
          {s.marks.map((m) => (
            <QuestionCard
              key={m.question_id}
              submissionId={id}
              mark={m}
              draft={drafts[m.question_id]}
              readOnly={finalized}
              categories={liveCategories}
              categoryState={categoryState}
              mistakesAnalysed={s.mistakes_analysed}
              onChange={(patch) =>
                setDrafts((prev) => ({
                  ...prev,
                  [m.question_id]: { ...prev[m.question_id], ...patch },
                }))
              }
            />
          ))}
        </section>
      </div>
    </div>
  );
}

/* One tagged mistake, with the two things a tutor may change about it
   (`AV-38`). Its own component, and its own mutation, because a question can
   carry several tags and a revision to one must not disable the others. */
function MistakeTag({
  submissionId,
  mistake,
  categories,
  categoryState,
}: {
  submissionId: number;
  mistake: MistakeRow;
  categories: MistakeCategoryItem[];
  categoryState: "loading" | "error" | "ready" | "none";
}) {
  const queryClient = useQueryClient();
  /* Revising a tag is not part of saving marks: it works on a finalized
     submission, it writes its own audit row, and nothing waits on it (AV-38).
     So it is its own mutation, fired on change rather than collected into the
     page's draft — there is no "finalize mistakes" step for it to wait for. */
  const revise = useMutation({
    mutationFn: (revision: { category_id: number; severity: number }) =>
      reviseMistake(submissionId, mistake.id, revision),
    /* Only this tag is taken from the response, merged into whatever is
       cached now. The response is the whole submission, and writing all of it
       would make two tags edited before either request returned overwrite each
       other: the later response carries the *other* tag as it was before its
       edit, so a saved decision would silently revert and the next change to
       it would send the reverted value.

       Merged rather than invalidated for the same reason the write is not
       just dropped: a refetch that fails after a successful PATCH leaves the
       controls re-enabled over the old tag, and the next change re-sends the
       stale counterpart. */
    onSuccess: (data) => {
      const revised = data.marks.flatMap((m) => m.mistakes).find((x) => x.id === mistake.id);
      if (!revised) return;
      queryClient.setQueryData(
        ["submission", submissionId],
        (prev: SubmissionDetail | undefined) =>
          prev && {
            ...prev,
            marks: prev.marks.map((m) => ({
              ...m,
              mistakes: m.mistakes.map((x) => (x.id === revised.id ? revised : x)),
            })),
          },
      );
    },
    // A rejected category is usually one archived in another tab since this
    // list was cached, which is permanent, not the transient failure the
    // message suggests — so drop the stale list rather than inviting a retry
    // that cannot succeed.
    onError: () => queryClient.invalidateQueries({ queryKey: ["mistake-categories"] }),
  });

  // The category picker needs the list; severity does not — it re-sends the
  // category the mistake already has, which the API accepts even when that
  // category has since been archived. So the two controls are disabled
  // independently, and the message below says which one is unavailable rather
  // than claiming nothing can be changed while severity plainly still can.
  const canPickCategory = categoryState === "ready";

  return (
    <div className="mt-3 rounded border border-line bg-surface-muted p-2">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm text-ink-700">Mistake</span>
        {/* `avora-control`, not `border-line-control`: the unlayered `.border`
            rule in index.css beats that layered utility and drew these at the
            hairline, under the 3:1 a control's edge needs. */}
        <select
          className="avora-control rounded border bg-surface px-2 py-1 text-sm disabled:opacity-50"
          aria-label="Mistake category"
          value={mistake.category_id}
          disabled={revise.isPending || !canPickCategory}
          onChange={(e) =>
            revise.mutate({ category_id: Number(e.target.value), severity: mistake.severity })
          }
        >
          {/* A category the tutor has since archived stays on the mistake it
              was tagged with and keeps counting — archiving is not deletion —
              but it is not in `categories`. Without an option for it the
              select falls back to its first one and shows a category nobody
              chose. (It could not *write* that category: both handlers read
              `mistake`, never the DOM. The damage is that the tutor is told
              the wrong thing.)

              Only once the list has actually loaded, though: while it is still
              empty every live category fails this test too, and the tutor
              would be told a category they are still using had been
              archived. */}
          {!canPickCategory ? (
            <option value={mistake.category_id}>{mistake.category_name}</option>
          ) : (
            !categories.some((c) => c.id === mistake.category_id) && (
              <option value={mistake.category_id}>{mistake.category_name} (archived)</option>
            )
          )}
          {categories.map((c) => (
            <option key={c.id} value={c.id!}>
              {c.name}
            </option>
          ))}
        </select>
        <select
          className="avora-control rounded border bg-surface px-2 py-1 text-sm disabled:opacity-50"
          aria-label="Severity"
          value={mistake.severity}
          disabled={revise.isPending}
          onChange={(e) =>
            revise.mutate({ category_id: mistake.category_id, severity: Number(e.target.value) })
          }
        >
          <option value={1}>Minor</option>
          <option value={2}>Moderate</option>
          <option value={3}>Major</option>
        </select>
        <span className="text-xs text-ink-500">{mistakeSourceLabel(mistake.source)}</span>
      </div>
      {mistake.note && (
        // SEC-20's flag-rather-than-obey half: the job saw something on the
        // page or in a category that read like an instruction. Nothing
        // downstream reads this, so if the tutor is not shown it, nobody ever
        // sees it.
        <p className="mt-2 rounded border border-warn-700 bg-warn-100 p-2 text-sm text-ink-900">
          <span className="font-medium">Flagged while tagging.</span> {mistake.note}
        </p>
      )}
      {categoryState === "none" && (
        <p className="mt-2 text-xs text-ink-500">
          Set up mistake categories for this subject to change the category.
        </p>
      )}
      {categoryState === "error" && (
        // Not the same as having none: saying so would be a false claim about
        // the tutor's own setup, and would send them to fix something that is
        // not broken.
        <p className="mt-2 text-xs text-ink-500">
          Your mistake categories didn't load, so the category can't be changed right now.
        </p>
      )}
      {revise.isError && (
        <p className="mt-2 text-sm text-risk-600">That change did not save. Try again.</p>
      )}
    </div>
  );
}

function QuestionCard({
  submissionId,
  mark,
  draft,
  readOnly,
  categories,
  categoryState,
  mistakesAnalysed,
  onChange,
}: {
  submissionId: number;
  mark: MarkRow;
  draft: Draft | undefined;
  readOnly: boolean;
  categories: MistakeCategoryItem[];
  categoryState: "loading" | "error" | "ready" | "none";
  mistakesAnalysed: boolean;
  onChange: (patch: Partial<Draft>) => void;
}) {
  const confidence = mark.ai_confidence ?? "unsure";
  const matchesAi = mark.ai_marks !== null && draft?.final_marks === mark.ai_marks;
  const [showHistory, setShowHistory] = useState(false);
  const marksId = useId();
  const history = useQuery({
    queryKey: ["mark-history", submissionId, mark.question_id],
    queryFn: () => markHistory(submissionId, mark.question_id),
    enabled: showHistory,
  });

  return (
    <div
      className={`rounded-xl border bg-surface p-4 shadow-[0_1px_2px_rgba(44,26,14,0.06)] ${
        mark.remark_requested
          ? "border-brand-600"
          : mark.needs_review
            ? "border-warn-700"
            : "border-line"
      }`}
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <span className="min-w-0 font-medium text-ink-900">
          Q{mark.number}{" "}
          <span className="font-normal text-ink-500">
            — {mark.text_summary} ({mark.max_marks} {mark.max_marks === 1 ? "mark" : "marks"})
          </span>
        </span>
        <div className="flex shrink-0 gap-1">
          {mark.auto_finalized && (
            <span className="rounded-full bg-ok-100 px-2 py-0.5 text-xs text-ok-700">Counted</span>
          )}
          <span className={`rounded-full px-2 py-0.5 text-xs ${CONFIDENCE_STYLE[confidence]}`}>
            {CONFIDENCE_LABEL[confidence]}
          </span>
        </div>
      </div>

      {mark.remark_requested && (
        <div className="mt-2 rounded border border-brand-500 bg-brand-50 p-2 text-sm text-ink-900">
          <span className="font-medium">The student asked you to look again.</span>
          {mark.remark_reason && <span> “{mark.remark_reason}”</span>}
        </div>
      )}

      {mark.scheme_conflict && (
        // The tutor's rule beat the official mark scheme here (AV-76, as the
        // owner revised it). The mark stands and counts — this is not a review
        // prompt — but a tutor who never sees this has no way to learn that a
        // rule they wrote is quietly marking their students differently from
        // the exam they will actually sit. Shown, never blocking.
        <div className="mt-2 rounded border border-warn-700 bg-warn-100 p-2 text-sm text-ink-900">
          <span className="font-medium">Marked by your rule, not the mark scheme.</span>{" "}
          {mark.scheme_conflict}
        </div>
      )}

      {mark.ai_transcription && (
        <div className="mt-2 rounded bg-surface-muted p-2 text-sm text-ink-700">
          <span className="font-medium text-ink-500">AI read:</span> {mark.ai_transcription}
        </div>
      )}

      <div className="mt-3 flex flex-wrap items-center gap-3">
        <label htmlFor={marksId} className="text-sm font-medium text-ink-900">
          Marks
        </label>
        <input
          id={marksId}
          type="number"
          min={0}
          max={mark.max_marks}
          disabled={readOnly}
          className={`${inputClasses.replace("w-full", "")} w-20 tabular-nums`}
          value={draft?.final_marks ?? ""}
          onChange={(e) =>
            onChange({
              final_marks: e.target.value === "" ? null : Number(e.target.value),
            })
          }
        />
        <span className="text-sm text-ink-500">/ {mark.max_marks}</span>
        {mark.ai_marks !== null &&
          !readOnly &&
          (matchesAi ? (
            <span className="rounded-md bg-ok-100 px-2 py-1 text-xs font-medium text-ok-700">
              Matches the AI's mark
            </span>
          ) : (
            <Button
              variant="secondary"
              size="sm"
              onClick={() => onChange({ final_marks: mark.ai_marks })}
            >
              Use the AI's mark ({mark.ai_marks}/{mark.max_marks})
            </Button>
          ))}
      </div>

      <Textarea
        disabled={readOnly}
        aria-label={`Feedback for the student on question ${mark.number}`}
        className="mt-3"
        rows={2}
        placeholder="Feedback for the student"
        value={draft?.final_feedback ?? ""}
        onChange={(e) => onChange({ final_feedback: e.target.value })}
      />

      {/* What went wrong, and the tutor's chance to disagree with it (AV-38).
          One block per tag, rendered only where there is one: a question that
          lost no marks has nothing to categorise, and an empty picker on every
          card would read as a demand to fill it in — which is exactly the
          prompt AV-38 says the tutor is never given. */}
      {mark.mistakes.map((mistake) => (
        <MistakeTag
          key={mistake.id}
          submissionId={submissionId}
          mistake={mistake}
          categories={categories}
          categoryState={categoryState}
        />
      ))}

      {/* Absent is shown as absent (PROD-2): with no tag and nothing having
          looked, the honest statement is that nobody has looked — not silence,
          which reads as a clean question. */}
      {mark.mistakes.length === 0 && !mistakesAnalysed && draft?.final_marks != null && (
        <p className="mt-3 text-xs text-ink-500">Not examined for mistakes yet.</p>
      )}

      <button
        type="button"
        aria-expanded={showHistory}
        onClick={() => setShowHistory((v) => !v)}
        className="mt-2 rounded text-xs font-medium text-ink-500 hover:text-ink-900"
      >
        {showHistory ? "Hide" : "Show"} mark history
      </button>
      <Reveal open={showHistory}>
        <ul className="space-y-1 pt-1 text-xs text-ink-700">
          {history.data?.map((h, i) => (
            <li key={i}>
              {h.old_marks} → {h.new_marks} by {h.changed_by_name} on{" "}
              {new Date(h.created_at).toLocaleDateString()}
              {h.reason === "remark_request" && " (remark request)"}
            </li>
          ))}
          {history.data?.length === 0 && (
            <li className="text-ink-500">This mark has never been changed.</li>
          )}
        </ul>
      </Reveal>
    </div>
  );
}
