import { useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { mySubmission, submitWork } from "../api/homework";
import { ApiError } from "../api/client";
import { PageUploader } from "./PageUploader";
import { Button } from "../ui";

export default function SubmitHomeworkPage() {
  const { assignmentId } = useParams();
  const id = Number(assignmentId);
  const queryClient = useQueryClient();

  const view = useQuery({
    queryKey: ["my-submission", id],
    queryFn: () => mySubmission(id),
    refetchInterval: (query) =>
      query.state.data?.status === "being_marked" ? 4000 : false,
  });

  const [files, setFiles] = useState<File[]>([]);
  const [error, setError] = useState<string | null>(null);

  const submit = useMutation({
    mutationFn: () => submitWork(id, files),
    onSuccess: () => {
      setFiles([]);
      queryClient.invalidateQueries({ queryKey: ["my-submission", id] });
      queryClient.invalidateQueries({ queryKey: ["my-assignments"] });
    },
    onError: (err) => setError(err instanceof ApiError ? err.message : String(err)),
  });

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (files.length) submit.mutate();
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
              <div key={m.number} className="rounded-lg border bg-white p-4">
                <div className="flex items-center justify-between">
                  <span className="font-medium text-slate-800">
                    Q{m.number}{" "}
                    <span className="font-normal text-slate-500">— {m.text_summary}</span>
                  </span>
                  <span className="text-sm font-medium text-slate-700">
                    {m.final_marks}/{m.max_marks}
                  </span>
                </div>
                {m.final_feedback && (
                  <p className="mt-2 text-sm text-slate-600">{m.final_feedback}</p>
                )}
              </div>
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
                Take clear photos or a scan of your handwritten answers. Photos straight from an
                iPhone are fine.
              </p>
              <form onSubmit={onSubmit} className="mt-4 space-y-4">
                <PageUploader files={files} onChange={setFiles} />
                {error && <p className="text-sm text-risk-600">{error}</p>}
                <Button type="submit" disabled={submit.isPending || files.length === 0}>
                  {submit.isPending ? "Uploading…" : "Submit work"}
                </Button>
              </form>
            </>
          )}
        </div>
      )}
    </div>
  );
}
