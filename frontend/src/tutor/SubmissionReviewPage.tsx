import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  finalizeSubmission,
  getSubmission,
  saveMarks,
  submissionFilePath,
  type MarkRow,
} from "../api/homework";
import { AuthImage, AuthFileLink } from "../components/AuthFile";
import { ApiError } from "../api/client";
import { useGroupContext } from "./GroupLayout";

interface Draft {
  final_marks: number | null;
  final_feedback: string;
}

const CONFIDENCE_STYLE: Record<string, string> = {
  high: "bg-green-100 text-green-700",
  medium: "bg-amber-100 text-amber-700",
  low: "bg-orange-100 text-orange-700",
  tutor_only: "bg-slate-200 text-slate-600",
};

const CONFIDENCE_LABEL: Record<string, string> = {
  high: "AI confident",
  medium: "AI unsure",
  low: "AI hard to read",
  tutor_only: "No mark scheme — mark yourself",
};

export default function SubmissionReviewPage() {
  const { submissionId } = useParams();
  const id = Number(submissionId);
  const { groupId } = useGroupContext();
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
          to={`/tutor/groups/${groupId}/homework/${s.assignment_id}`}
          className="text-sm text-brand-600 hover:underline"
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
            AI draft — review and confirm each mark
          </h3>
          {s.marks.map((m) => (
            <QuestionCard
              key={m.question_id}
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
  mark,
  draft,
  readOnly,
  onChange,
}: {
  mark: MarkRow;
  draft: Draft | undefined;
  readOnly: boolean;
  onChange: (patch: Partial<Draft>) => void;
}) {
  const confidence = mark.ai_confidence ?? "tutor_only";
  const matchesAi =
    mark.ai_marks !== null && draft?.final_marks === mark.ai_marks;

  return (
    <div className="rounded-lg border bg-white p-4">
      <div className="flex items-center justify-between">
        <span className="font-medium text-slate-800">
          Q{mark.number}{" "}
          <span className="font-normal text-slate-500">
            — {mark.text_summary} ({mark.max_marks} marks)
          </span>
        </span>
        <span
          className={`rounded-full px-2 py-0.5 text-xs ${CONFIDENCE_STYLE[confidence]}`}
        >
          {CONFIDENCE_LABEL[confidence]}
        </span>
      </div>

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
    </div>
  );
}
