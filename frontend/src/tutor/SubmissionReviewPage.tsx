import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  finalizeSubmission,
  getSubmission,
  markHistory,
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
  high: "bg-green-100 text-green-700",
  medium: "bg-green-100 text-green-700",
  low: "bg-orange-100 text-orange-700",
  unsure: "bg-slate-200 text-slate-600",
  tutor_only: "bg-slate-200 text-slate-600",
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

  const submission = useQuery({
    queryKey: ["submission", id],
    queryFn: () => getSubmission(id),
  });

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
    submission.data?.marks.filter((m) => m.needs_review || m.remark_requested)
      .length ?? 0;

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

  const finalize = useMutation({
    mutationFn: async () => {
      await saveMarks(
        id,
        Object.entries(drafts).map(([qid, d]) => ({
          question_id: Number(qid),
          final_marks: d.final_marks,
          final_feedback: d.final_feedback || null,
        })),
      );
      return finalizeSubmission(id);
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["submission", id] }),
    onError: (err) => setError(err instanceof ApiError ? err.message : String(err)),
  });

  const totals = useMemo(() => {
    if (!submission.data) return { got: 0, max: 0 };
    let got = 0;
    let max = 0;
    for (const m of submission.data.marks) {
      max += m.max_marks;
      got += drafts[m.question_id]?.final_marks ?? 0;
    }
    return { got, max };
  }, [submission.data, drafts]);

  if (submission.isLoading) return <p className="text-slate-500">Loading…</p>;
  if (submission.isError || !submission.data)
    return <p className="text-red-600">Submission not found.</p>;
  const s = submission.data;

  return (
    <div className="space-y-5">
      <div>
        <Link
          to={
            s.assignment_id
              ? `/tutor/assignments/${s.assignment_id}`
              : "/tutor/past-papers"
          }
          className="text-sm text-blue-600 hover:underline"
        >
          ← {s.assignment_title}
        </Link>
        <div className="mt-1 flex items-center justify-between">
          <h2 className="text-xl font-semibold text-slate-800">
            {s.student_name}'s work
          </h2>
          <div className="flex items-center gap-3 text-sm">
            <span className="font-medium text-slate-700">
              {totals.got} / {totals.max}
            </span>
            {autoFinalized && (
              <span className="rounded-full bg-green-100 px-3 py-1 text-xs font-medium text-green-700">
                Marked automatically
              </span>
            )}
            {finalized ? (
              <span className="rounded-full bg-green-100 px-3 py-1 text-xs font-medium text-green-700">
                Finalized
              </span>
            ) : (
              <>
                <button
                  onClick={() => save.mutate()}
                  disabled={save.isPending}
                  className="rounded border border-slate-300 px-3 py-1.5 hover:bg-slate-50 disabled:opacity-50"
                >
                  Save draft
                </button>
                <button
                  onClick={() => finalize.mutate()}
                  disabled={finalize.isPending}
                  className="rounded bg-blue-600 px-3 py-1.5 text-white hover:bg-blue-700 disabled:opacity-50"
                >
                  Finalize marks
                </button>
              </>
            )}
          </div>
        </div>
      </div>

      {s.ai_error && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
          AI marking did not run ({s.ai_error}). Mark each question yourself below.
        </div>
      )}
      {error && <p className="text-sm text-red-600">{error}</p>}

      <div className="grid gap-5 lg:grid-cols-2">
        {/* Left: the student's uploaded pages */}
        <div className="space-y-3">
          <h3 className="text-sm font-medium text-slate-600">Uploaded pages</h3>
          {s.files.map((f) =>
            f.mime === "application/pdf" ? (
              <div key={f.id} className="rounded border bg-white p-3 text-sm">
                <AuthFileLink path={submissionFilePath(s.id, f.id)} label={`Open ${f.name}`} />
              </div>
            ) : (
              <AuthImage key={f.id} path={submissionFilePath(s.id, f.id)} alt={f.name} />
            ),
          )}
        </div>

        {/* Right: AI reading + tutor's editable marks, question by question */}
        <div className="space-y-3">
          <h3 className="text-sm font-medium text-slate-600">
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
  const matchesAi =
    mark.ai_marks !== null && draft?.final_marks === mark.ai_marks;
  const [showHistory, setShowHistory] = useState(false);
  const history = useQuery({
    queryKey: ["mark-history", submissionId, mark.question_id],
    queryFn: () => markHistory(submissionId, mark.question_id),
    enabled: showHistory,
  });

  return (
    <div
      className={`rounded-lg border bg-white p-4 ${
        mark.remark_requested
          ? "border-purple-300"
          : mark.needs_review
            ? "border-amber-300"
            : ""
      }`}
    >
      <div className="flex items-center justify-between">
        <span className="font-medium text-slate-800">
          Q{mark.number}{" "}
          <span className="font-normal text-slate-500">
            — {mark.text_summary} ({mark.max_marks} marks)
          </span>
        </span>
        <div className="flex gap-1">
          {mark.auto_finalized && (
            <span className="rounded-full bg-green-50 px-2 py-0.5 text-xs text-green-700">
              Counted
            </span>
          )}
          <span
            className={`rounded-full px-2 py-0.5 text-xs ${CONFIDENCE_STYLE[confidence]}`}
          >
            {CONFIDENCE_LABEL[confidence]}
          </span>
        </div>
      </div>

      {mark.remark_requested && (
        <div className="mt-2 rounded border border-purple-200 bg-purple-50 p-2 text-sm text-purple-900">
          <span className="font-medium">The student asked you to look again.</span>
          {mark.remark_reason && <span> “{mark.remark_reason}”</span>}
        </div>
      )}

      {mark.ai_transcription && (
        <div className="mt-2 rounded bg-slate-50 p-2 text-sm text-slate-600">
          <span className="font-medium text-slate-500">AI read:</span> {mark.ai_transcription}
        </div>
      )}

      <div className="mt-3 flex flex-wrap items-center gap-3">
        <label className="text-sm text-slate-600">Marks</label>
        <input
          type="number"
          min={0}
          max={mark.max_marks}
          disabled={readOnly}
          className="w-20 rounded border border-slate-300 px-2 py-1 text-sm disabled:bg-slate-50"
          value={draft?.final_marks ?? ""}
          onChange={(e) =>
            onChange({
              final_marks: e.target.value === "" ? null : Number(e.target.value),
            })
          }
        />
        <span className="text-sm text-slate-400">/ {mark.max_marks}</span>
        {mark.ai_marks !== null && !readOnly && (
          <button
            onClick={() => onChange({ final_marks: mark.ai_marks })}
            className={`rounded px-2 py-1 text-xs ${
              matchesAi
                ? "bg-green-100 text-green-700"
                : "bg-slate-100 text-slate-600 hover:bg-slate-200"
            }`}
          >
            {matchesAi ? "✓ matches AI" : `Accept AI (${mark.ai_marks})`}
          </button>
        )}
      </div>

      <textarea
        disabled={readOnly}
        className="mt-2 w-full rounded border border-slate-300 px-2 py-1 text-sm disabled:bg-slate-50"
        rows={2}
        placeholder="Feedback for the student"
        value={draft?.final_feedback ?? ""}
        onChange={(e) => onChange({ final_feedback: e.target.value })}
      />

      <button
        onClick={() => setShowHistory((v) => !v)}
        className="mt-2 text-xs text-slate-500 hover:underline"
      >
        {showHistory ? "Hide" : "Show"} mark history
      </button>
      {showHistory && (
        <ul className="mt-1 space-y-1 text-xs text-slate-600">
          {history.data?.map((h, i) => (
            <li key={i}>
              {h.old_marks} → {h.new_marks} by {h.changed_by_name} on{" "}
              {new Date(h.created_at).toLocaleDateString()}
              {h.reason === "remark_request" && " (remark request)"}
            </li>
          ))}
          {history.data?.length === 0 && (
            <li className="text-slate-400">This mark has never been changed.</li>
          )}
        </ul>
      )}
    </div>
  );
}
