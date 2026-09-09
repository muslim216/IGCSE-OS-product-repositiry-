import { useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  MAX_TYPED_ANSWER,
  mySubmission,
  requestRemark,
  submitWork,
  type StudentMarkRow,
} from "../api/homework";
import { ApiError } from "../api/client";

export default function SubmitHomeworkPage() {
  const { assignmentId } = useParams();
  const id = Number(assignmentId);
  const queryClient = useQueryClient();

  const view = useQuery({
    queryKey: ["my-submission", id],
    queryFn: () => mySubmission(id),
    refetchInterval: (query) => (query.state.data?.status === "being_marked" ? 4000 : false),
  });

  const [files, setFiles] = useState<File[]>([]);
  const [typed, setTyped] = useState("");
  const [error, setError] = useState<string | null>(null);

  const submit = useMutation({
    mutationFn: () => submitWork(id, files, typed),
    onSuccess: () => {
      setFiles([]);
      setTyped("");
      queryClient.invalidateQueries({ queryKey: ["my-submission", id] });
      queryClient.invalidateQueries({ queryKey: ["my-assignments"] });
    },
    onError: (err) => setError(err instanceof ApiError ? err.message : String(err)),
  });

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    // Either channel, or both (AV-73) — the server enforces the same rule.
    if (files.length || typed.trim()) submit.mutate();
  }

  if (view.isLoading) return <p className="text-slate-500">Loading…</p>;
  if (view.isError || !view.data) return <p className="text-red-600">Homework not found.</p>;
  const v = view.data;

  return (
    <div className="max-w-2xl space-y-5">
      <Link to="/student/homework" className="text-sm text-blue-600 hover:underline">
        ← Your homework
      </Link>

      {v.status === "marked" ? (
        <div>
          <h2 className="text-xl font-semibold text-slate-800">Your marked homework</h2>
          <p className="mt-1 text-lg font-medium text-slate-700">
            {v.total} / {v.total_max}
          </p>
          <div className="mt-4 space-y-3">
            {v.marks.map((m) => (
              <MarkedQuestion
                key={m.number}
                submissionId={v.submission_id}
                mark={m}
                assignmentId={id}
              />
            ))}
          </div>
        </div>
      ) : (
        <div>
          <h2 className="text-xl font-semibold text-slate-800">Submit your homework</h2>
          {v.status === "being_marked" ? (
            <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">
              Your work is submitted and being marked by your tutor. You'll see your marks and
              feedback here once it's ready. (This page refreshes automatically.)
            </div>
          ) : (
            <>
              {v.status === "submitted" && (
                <div className="mt-3 rounded-lg border border-blue-200 bg-blue-50 p-3 text-sm text-blue-700">
                  Submitted. You can re-upload before it's marked if you need to.
                </div>
              )}
              <p className="mt-2 text-sm text-slate-500">
                Take clear photos or a scan of your handwritten answers (JPG, PNG or PDF), upload
                every page in order — or type your answers below. You can do both.
              </p>
              <form onSubmit={onSubmit} className="mt-4 space-y-3">
                <input
                  type="file"
                  multiple
                  accept="application/pdf,image/*,.heic,.heif"
                  onChange={(e) => setFiles(Array.from(e.target.files ?? []))}
                  className="text-sm"
                />
                {files.length > 0 && (
                  <p className="text-sm text-slate-500">
                    {files.length} file{files.length === 1 ? "" : "s"} selected
                  </p>
                )}
                <label className="block text-sm">
                  <span className="mb-1 block text-slate-600">Or type your answers</span>
                  <textarea
                    rows={10}
                    maxLength={MAX_TYPED_ANSWER}
                    value={typed}
                    onChange={(e) => setTyped(e.target.value)}
                    placeholder={"1. ...\n2. ..."}
                    className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
                  />
                </label>
                {/* AV-92: marks and feedback appear only after the tutor signs
                    off, and there is deliberately no in-progress feedback here.
                    Saying so is better than a student wondering whether typing
                    more will show them something. */}
                <p className="text-xs text-slate-500">
                  You'll see your marks once your tutor has finished — nothing is shown while you're
                  still working.
                </p>
                {error && <p className="text-sm text-red-600">{error}</p>}
                <button
                  type="submit"
                  disabled={submit.isPending || (files.length === 0 && typed.trim() === "")}
                  className="rounded-md bg-blue-600 px-4 py-2 font-medium text-white hover:bg-blue-700 disabled:opacity-50"
                >
                  {submit.isPending ? "Uploading…" : "Submit work"}
                </button>
              </form>
            </>
          )}
        </div>
      )}
    </div>
  );
}

function MarkedQuestion({
  submissionId,
  assignmentId,
  mark,
}: {
  submissionId: number | null;
  assignmentId: number;
  mark: StudentMarkRow;
}) {
  const queryClient = useQueryClient();
  const [asking, setAsking] = useState(false);
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);

  const ask = useMutation({
    mutationFn: () => requestRemark(submissionId!, mark.question_id!, reason),
    onSuccess: () => {
      setAsking(false);
      queryClient.invalidateQueries({ queryKey: ["my-submission", assignmentId] });
    },
    onError: (err) => setError(err instanceof ApiError ? err.message : String(err)),
  });

  const canAsk = submissionId !== null && mark.question_id !== null && mark.remark_status === null;

  return (
    <div className="rounded-lg border bg-white p-4">
      <div className="flex items-center justify-between">
        <span className="font-medium text-slate-800">
          Q{mark.number} <span className="font-normal text-slate-500">— {mark.text_summary}</span>
        </span>
        <span className="text-sm font-medium text-slate-700">
          {mark.final_marks}/{mark.max_marks}
        </span>
      </div>
      {mark.final_feedback && <p className="mt-2 text-sm text-slate-600">{mark.final_feedback}</p>}

      {mark.remark_status === "open" && (
        <p className="mt-2 text-sm text-purple-700">
          Your tutor has been asked to look at this one again.
        </p>
      )}
      {mark.remark_status === "resolved" && (
        <p className="mt-2 text-sm text-slate-500">
          Your tutor has already re-checked this question.
        </p>
      )}

      {canAsk &&
        (asking ? (
          <div className="mt-3 space-y-2">
            <textarea
              className="w-full rounded border border-slate-300 px-2 py-1 text-sm"
              rows={2}
              placeholder="Why do you think this mark should change? (optional)"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
            {error && <p className="text-sm text-red-600">{error}</p>}
            <div className="flex gap-2">
              <button
                onClick={() => ask.mutate()}
                disabled={ask.isPending}
                className="rounded bg-blue-600 px-3 py-1 text-sm text-white hover:bg-blue-700 disabled:opacity-50"
              >
                Send to my tutor
              </button>
              <button
                onClick={() => setAsking(false)}
                className="rounded border border-slate-300 px-3 py-1 text-sm hover:bg-slate-50"
              >
                Cancel
              </button>
            </div>
            <p className="text-xs text-slate-500">
              Your tutor decides — you can only ask once per question.
            </p>
          </div>
        ) : (
          <button
            onClick={() => setAsking(true)}
            className="mt-2 text-xs text-blue-600 hover:underline"
          >
            Request a remark
          </button>
        ))}
    </div>
  );
}
