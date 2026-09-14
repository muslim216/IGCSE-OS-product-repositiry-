import { useEffect, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getMock, mockPaperPath, myMockSubmission, openMock, sitMock } from "../api/mocks";
import { AuthFileLink } from "../components/AuthFile";
import { ApiError } from "../api/client";

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
    staleTime: Infinity,
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
  const [typed, setTyped] = useState("");
  const [error, setError] = useState<string | null>(null);

  const submit = useMutation({
    mutationFn: () => sitMock(id, files, typed),
    onSuccess: () => {
      setFiles([]);
      setTyped("");
      queryClient.invalidateQueries({ queryKey: ["my-mock-submission", id] });
    },
    onError: (err) => setError(err instanceof ApiError ? err.message : String(err)),
  });

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (files.length || typed.trim()) submit.mutate();
  }

  if (mock.isLoading) return <p className="text-ink-500">Loading…</p>;
  if (mock.isError || !mock.data) return <p className="text-risk-600">Mock not found.</p>;
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

  return (
    <div className="max-w-2xl space-y-5">
      <Link to="/student/mocks" className="text-sm text-brand-600 hover:underline">
        ← Mocks
      </Link>

      <div>
        <h2 className="text-xl font-semibold text-ink-900">{m.title}</h2>
        <p className="text-sm text-ink-500">
          {m.total_marks ? `${m.total_marks} marks` : ""}
          {m.duration_minutes ? ` · ${m.duration_minutes} minutes allowed` : ""}
        </p>
        <div className="mt-2 text-sm">
          <AuthFileLink path={mockPaperPath(m.id)} label="Open the question paper" />
        </div>
      </div>

      {timeUp ? (
        <div className="rounded-lg border border-line bg-warn-100 p-4 text-sm text-warn-700">
          Your time is up. You can still hand in — your tutor will see it came in late.
        </div>
      ) : secondsLeft !== null ? (
        <div className="rounded-lg border border-line bg-surface p-4">
          <div className="text-sm text-ink-500">Time left</div>
          <div className="text-2xl font-semibold tabular-nums text-ink-900">
            {formatLeft(secondsLeft)}
          </div>
          <p className="mt-1 text-xs text-ink-500">
            Timed on our servers, so closing this page doesn't buy you more time.
          </p>
        </div>
      ) : null}

      {sub ? (
        <div className="rounded-lg border border-line bg-surface p-4">
          <h3 className="font-medium text-ink-900">Handed in</h3>
          {/* Measured by us from the clock, so it is stated plainly — unlike a
              past paper's self-declared minutes, which carry a caveat
              (`PROD-8`, `UX-20`). Absent stays absent (`PROD-2`). */}
          {sub.measured_minutes !== null && sub.measured_minutes !== undefined && (
            <p className="mt-1 text-sm text-ink-700">You took {sub.measured_minutes} minutes.</p>
          )}
          {sub.submitted_late && (
            <p className="mt-1 text-sm text-warn-700">
              This came in after your time was up, so it's flagged for your tutor. It is still
              marked in full.
            </p>
          )}
          <p className="mt-3 text-sm text-ink-500">
            Your per-question marks and feedback appear in your progress once it has been marked.
          </p>
        </div>
      ) : (
        <form
          onSubmit={onSubmit}
          className="space-y-3 rounded-lg border border-line bg-surface p-4"
        >
          <h3 className="font-medium text-ink-900">Hand in your answers</h3>
          <p className="text-sm text-ink-500">
            Upload clear photos or a scan of every page of your answers, in order — or type them
            below.
          </p>
          <input
            type="file"
            multiple
            accept="application/pdf,image/*"
            onChange={(e) => setFiles(Array.from(e.target.files ?? []))}
            className="block text-sm"
          />
          {files.length > 0 && (
            <p className="text-sm text-ink-500">
              {files.length} file{files.length === 1 ? "" : "s"} selected
            </p>
          )}

          <label className="block text-sm text-ink-700">
            Or type your answers
            <textarea
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
              rows={6}
              className="mt-1 block w-full rounded border border-line-control px-2 py-1 text-sm"
            />
          </label>

          {error && <p className="text-sm text-risk-600">{error}</p>}
          {/* Never disabled by the clock. A late hand-in is accepted in full and
              flagged for the tutor — blocking it is the failure this feature
              exists to prevent. */}
          <button
            type="submit"
            disabled={submit.isPending || (files.length === 0 && typed.trim() === "")}
            className="rounded-md bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50"
          >
            {submit.isPending ? "Handing in…" : "Hand in"}
          </button>
        </form>
      )}
    </div>
  );
}
