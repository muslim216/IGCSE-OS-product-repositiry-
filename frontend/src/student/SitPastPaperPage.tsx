import { useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  getPastPaper,
  logAttempt,
  myAttempt,
  pastPaperBookletPath,
} from "../api/pastPapers";
import { AuthFileLink } from "../components/AuthFile";
import { ApiError } from "../api/client";

export default function SitPastPaperPage() {
  const { pastPaperId } = useParams();
  const id = Number(pastPaperId);
  const queryClient = useQueryClient();

  const paper = useQuery({ queryKey: ["past-paper", id], queryFn: () => getPastPaper(id) });
  const attempt = useQuery({
    queryKey: ["past-paper-attempt", id],
    queryFn: () => myAttempt(id),
    refetchInterval: (query) =>
      query.state.data?.status === "being_marked" ? 4000 : false,
  });

  const [files, setFiles] = useState<File[]>([]);
  const [attemptedAt, setAttemptedAt] = useState(
    () => new Date().toISOString().slice(0, 10),
  );
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
    onError: (err) => setError(err instanceof ApiError ? err.message : String(err)),
  });

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (files.length) submit.mutate();
  }

  if (paper.isLoading) return <p className="text-slate-500">Loading…</p>;
  if (paper.isError || !paper.data)
    return <p className="text-red-600">Past paper not found.</p>;
  const p = paper.data;
  const a = attempt.data;

  return (
    <div className="max-w-2xl space-y-5">
      <Link to="/student/past-papers" className="text-sm text-blue-600 hover:underline">
        ← Past papers
      </Link>

      <div>
        <h2 className="text-xl font-semibold text-slate-800">
          {p.session_label} · {p.paper_number}
        </h2>
        <p className="text-sm text-slate-500">
          {p.total_marks ? `${p.total_marks} marks` : ""}
          {p.duration_minutes ? ` · ${p.duration_minutes} minutes allowed` : ""}
        </p>
        <div className="mt-2 text-sm">
          <AuthFileLink path={pastPaperBookletPath(p.id)} label="Open the question paper" />
        </div>
      </div>

      {a?.status === "marked" ? (
        <div className="rounded-lg border bg-white p-4">
          <h3 className="font-medium text-slate-800">Your result</h3>
          <p className="mt-1 text-lg font-medium text-slate-700">
            {a.raw_marks} / {a.max_marks}
          </p>
          <p className="mt-1 text-sm text-slate-500">
            Sat {a.attempted_at}
            {a.timed ? " under timed conditions" : " untimed"}
            {a.time_taken_minutes ? ` · took ${a.time_taken_minutes} minutes` : ""}
          </p>
          <p className="mt-3 text-sm text-slate-500">
            Your per-question marks and feedback are in your readiness
            breakdown.
          </p>
        </div>
      ) : a?.status === "being_marked" ? (
        <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">
          Your answers are being marked. This page refreshes automatically.
        </div>
      ) : (
        <form onSubmit={onSubmit} className="space-y-3 rounded-lg border bg-white p-4">
          <h3 className="font-medium text-slate-800">Log your attempt</h3>
          <p className="text-sm text-slate-500">
            Upload clear photos or a scan of every page of your answers, in
            order.
          </p>
          <input
            type="file"
            multiple
            accept="application/pdf,image/*"
            onChange={(e) => setFiles(Array.from(e.target.files ?? []))}
            className="block text-sm"
          />
          {files.length > 0 && (
            <p className="text-sm text-slate-500">
              {files.length} file{files.length === 1 ? "" : "s"} selected
            </p>
          )}

          <div className="grid gap-3 sm:grid-cols-2">
            <label className="text-sm text-slate-600">
              When did you sit it?
              <input
                type="date"
                value={attemptedAt}
                onChange={(e) => setAttemptedAt(e.target.value)}
                className="mt-1 block w-full rounded border border-slate-300 px-2 py-1 text-sm"
              />
            </label>
            <label className="text-sm text-slate-600">
              How long did it take? (minutes)
              <input
                type="number"
                min={1}
                value={minutes}
                onChange={(e) => setMinutes(e.target.value)}
                placeholder="Optional"
                className="mt-1 block w-full rounded border border-slate-300 px-2 py-1 text-sm"
              />
            </label>
          </div>

          <label className="flex items-center gap-2 text-sm text-slate-600">
            <input
              type="checkbox"
              checked={timed}
              onChange={(e) => setTimed(e.target.checked)}
            />
            I sat this under timed exam conditions
          </label>
          <p className="text-xs text-slate-400">
            We take your word for this — be honest, it changes what your
            readiness score means.
          </p>

          {error && <p className="text-sm text-red-600">{error}</p>}
          <button
            type="submit"
            disabled={submit.isPending || files.length === 0}
            className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {submit.isPending ? "Uploading…" : "Submit for marking"}
          </button>
        </form>
      )}
    </div>
  );
}
