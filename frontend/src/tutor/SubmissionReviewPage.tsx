import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  finalizeSubmission,
  getSubmission,
  markHistory,
  reviewQueue,
  saveMarks,
  submissionFilePath,
  type MarkRow,
} from "../api/homework";
import { AuthImage, AuthFileLink } from "../components/AuthFile";
import { ApiError } from "../api/client";

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

  const queueItems = queue.data ?? [];
  const position = queueItems.findIndex((item) => item.submission_id === id);
  const next = position >= 0 ? queueItems[position + 1] : undefined;

  const goNext = () => {
    if (next) navigate(`/tutor/submissions/${next.submission_id}?queue=review`);
    else navigate("/tutor/review");
  };

  const [drafts, setDrafts] = useState<Record<number, Draft>>({});
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (submission.data) {
      const next: Record<number, Draft> = {};
      for (const m of submission.data.marks) {
        // Seed the tutor's editable value from any saved final, else the AI proposal.
        next[m.question_id] = {
          final_marks: m.final_marks ?? m.ai_marks,
          final_feedback: m.final_feedback ?? m.ai_feedback ?? "",
        };
      }
      setDrafts(next);
    }
  }, [submission.data]);

  const finalized = submission.data?.status === "finalized";
  const autoFinalized = submission.data?.status === "auto_finalized";
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
    onError: (err) => setError(err instanceof ApiError ? err.message : String(err)),
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
    onError: (err) => setError(err instanceof ApiError ? err.message : String(err)),
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

  if (submission.isLoading) return <p className="text-ink-500">Loading…</p>;
  if (submission.isError || !submission.data)
    return <p className="text-risk-600">Submission not found.</p>;
  const s = submission.data;

  return (
    <div className="space-y-5">
      <div>
        {/* In a queue the breadcrumb returns to the queue, not the assignment:
            six submissions used to cost six round trips back out through their
            parent assignment to find the next one. */}
        <div className="flex flex-wrap items-center justify-between gap-2">
          <Link
            to={
              inQueue
                ? "/tutor/review"
                : s.assignment_id
                  ? `/tutor/assignments/${s.assignment_id}`
                  : "/tutor/past-papers"
            }
            className="text-sm text-brand-600 hover:underline"
          >
            ← {inQueue ? "Review queue" : s.assignment_title}
          </Link>
          {inQueue && position >= 0 && (
            <span className="text-sm text-ink-500">
              Reviewing {position + 1} of {queueItems.length}
            </span>
          )}
        </div>
        <div className="mt-1 flex items-center justify-between">
          <h2 className="text-xl font-semibold text-ink-900">{s.student_name}'s work</h2>
          <div className="flex items-center gap-3 text-sm">
            <span className="font-medium text-ink-700">
              {totals.got} / {totals.max}
              {totals.unmarked > 0 && (
                <span className="ml-1.5 font-normal text-ink-500">
                  ({totals.unmarked} not marked yet)
                </span>
              )}
            </span>
            {autoFinalized && (
              <span className="rounded-full bg-ok-100 px-3 py-1 text-xs font-medium text-ok-700">
                Marked automatically
              </span>
            )}
            {finalized ? (
              <>
                <span className="rounded-full bg-ok-100 px-3 py-1 text-xs font-medium text-ok-700">
                  Finalized
                </span>
                {inQueue && (
                  <button
                    onClick={goNext}
                    className="rounded border border-line-control px-3 py-1.5 hover:bg-surface-muted"
                  >
                    {next ? "Next →" : "Back to queue"}
                  </button>
                )}
              </>
            ) : (
              <>
                <button
                  onClick={() => save.mutate()}
                  disabled={save.isPending}
                  className="rounded border border-line-control px-3 py-1.5 hover:bg-surface-muted disabled:opacity-50"
                >
                  Save draft
                </button>
                {inQueue && (
                  // Skip leaves the marks exactly as they are — it is "not now",
                  // never a decision, so it must not write anything.
                  <button
                    onClick={goNext}
                    className="rounded border border-line-control px-3 py-1.5 hover:bg-surface-muted"
                  >
                    Skip
                  </button>
                )}
                <button
                  onClick={() => finalize.mutate(inQueue)}
                  disabled={finalize.isPending}
                  className="rounded bg-brand-600 px-3 py-1.5 text-canvas hover:bg-brand-700 disabled:opacity-50"
                >
                  {inQueue ? (next ? "Finalize & next" : "Finalize & finish") : "Finalize marks"}
                </button>
              </>
            )}
          </div>
        </div>
      </div>

      {s.ai_error && (
        <div className="rounded-lg border border-line bg-warn-100 p-3 text-sm text-warn-700">
          AI marking did not run ({s.ai_error}). Mark each question yourself below.
        </div>
      )}
      {error && <p className="text-sm text-risk-600">{error}</p>}

      <div className="grid gap-5 lg:grid-cols-2">
        {/* Left: the student's uploaded pages */}
        <div className="space-y-3">
          <h3 className="text-sm font-medium text-ink-700">Uploaded pages</h3>
          {s.files.map((f) =>
            f.mime === "application/pdf" ? (
              <div key={f.id} className="rounded border border-line bg-surface p-3 text-sm">
                <AuthFileLink path={submissionFilePath(s.id, f.id)} label={`Open ${f.name}`} />
              </div>
            ) : (
              <AuthImage key={f.id} path={submissionFilePath(s.id, f.id)} alt={f.name} />
            ),
          )}
        </div>

        {/* Right: AI reading + tutor's editable marks, question by question */}
        <div className="space-y-3">
          <h3 className="text-sm font-medium text-ink-700">
            {reviewCount > 0
              ? `${reviewCount} of ${s.marks.length} marks need your decision`
              : "Every mark was made confidently — nothing needs your decision"}
          </h3>
          {s.marks.map((m) => (
            <QuestionCard
              key={m.question_id}
              submissionId={id}
              mark={m}
              draft={drafts[m.question_id]}
              readOnly={finalized}
              onChange={(patch) =>
                setDrafts((prev) => ({
                  ...prev,
                  [m.question_id]: { ...prev[m.question_id], ...patch },
                }))
              }
            />
          ))}
        </div>
      </div>
    </div>
  );
}

function QuestionCard({
  submissionId,
  mark,
  draft,
  readOnly,
  onChange,
}: {
  submissionId: number;
  mark: MarkRow;
  draft: Draft | undefined;
  readOnly: boolean;
  onChange: (patch: Partial<Draft>) => void;
}) {
  const confidence = mark.ai_confidence ?? "unsure";
  const matchesAi = mark.ai_marks !== null && draft?.final_marks === mark.ai_marks;
  const [showHistory, setShowHistory] = useState(false);
  const history = useQuery({
    queryKey: ["mark-history", submissionId, mark.question_id],
    queryFn: () => markHistory(submissionId, mark.question_id),
    enabled: showHistory,
  });

  return (
    <div
      className={`rounded-lg border border-line bg-surface p-4 ${
        mark.remark_requested ? "border-brand-600" : mark.needs_review ? "border-warn-700" : ""
      }`}
    >
      <div className="flex items-center justify-between">
        <span className="font-medium text-ink-900">
          Q{mark.number}{" "}
          <span className="font-normal text-ink-500">
            — {mark.text_summary} ({mark.max_marks} marks)
          </span>
        </span>
        <div className="flex gap-1">
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

      {mark.ai_transcription && (
        <div className="mt-2 rounded bg-surface-muted p-2 text-sm text-ink-700">
          <span className="font-medium text-ink-500">AI read:</span> {mark.ai_transcription}
        </div>
      )}

      <div className="mt-3 flex flex-wrap items-center gap-3">
        <label className="text-sm text-ink-700">Marks</label>
        <input
          type="number"
          min={0}
          max={mark.max_marks}
          disabled={readOnly}
          className="w-20 rounded border border-line-control px-2 py-1 text-sm disabled:bg-surface-muted"
          value={draft?.final_marks ?? ""}
          onChange={(e) =>
            onChange({
              final_marks: e.target.value === "" ? null : Number(e.target.value),
            })
          }
        />
        <span className="text-sm text-ink-500">/ {mark.max_marks}</span>
        {mark.ai_marks !== null && !readOnly && (
          <button
            onClick={() => onChange({ final_marks: mark.ai_marks })}
            className={`rounded px-2 py-1 text-xs ${
              matchesAi ? "bg-ok-100 text-ok-700" : "bg-surface-muted text-ink-700 hover:bg-line"
            }`}
          >
            {matchesAi ? "✓ matches AI" : `Accept AI (${mark.ai_marks})`}
          </button>
        )}
      </div>

      <textarea
        disabled={readOnly}
        className="mt-2 w-full rounded border border-line-control px-2 py-1 text-sm disabled:bg-surface-muted"
        rows={2}
        placeholder="Feedback for the student"
        value={draft?.final_feedback ?? ""}
        onChange={(e) => onChange({ final_feedback: e.target.value })}
      />

      <button
        onClick={() => setShowHistory((v) => !v)}
        className="mt-2 text-xs text-ink-500 hover:underline"
      >
        {showHistory ? "Hide" : "Show"} mark history
      </button>
      {showHistory && (
        <ul className="mt-1 space-y-1 text-xs text-ink-700">
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
      )}
    </div>
  );
}
