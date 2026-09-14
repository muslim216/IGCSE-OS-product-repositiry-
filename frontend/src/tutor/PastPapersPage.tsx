import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  hidePastPaper,
  listPastPapers,
  pastPaperPaperPath,
  pastPaperMarkSchemePath,
  uploadPastPaper,
} from "../api/pastPapers";
import { listSubjects } from "../api/groups";
import { AuthFileLink } from "../components/AuthFile";
import { ApiError } from "../api/client";

type PaperRow = NonNullable<Awaited<ReturnType<typeof listPastPapers>>>[number];

/** The one status line a paper gets — never two.
 *
 * Written as early returns rather than nested ternaries because the ordering
 * *is* the rule: a failed paper keeps the name "Untitled paper" and a question
 * count of zero, since the AI reads the name and the questions in the same pass
 * and failing loses both. Those are the same two signals the in-progress state
 * has, so a shape that can evaluate more than one branch tells a tutor it is
 * still working when it has already given up — which it did, until this was a
 * single exclusive branch.
 */
function statusLine(p: PaperRow): string {
  if (p.extraction_error) return `Couldn't read this paper: ${p.extraction_error}`;
  if (p.question_count > 0) {
    const marks = p.total_marks ? ` · ${p.total_marks} marks` : "";
    return `${p.question_count} questions${marks}`;
  }
  return "Reading the questions out of the paper…";
}

export default function PastPapersPage() {
  const queryClient = useQueryClient();
  const papers = useQuery({
    queryKey: ["past-papers"],
    queryFn: () => listPastPapers(),
    // Extraction happens in a background job, so without this the tutor sits on
    // "Reading the questions…" until they navigate away and back. Self-
    // terminating: once nothing is mid-extraction the interval returns false.
    refetchInterval: (query) =>
      query.state.data?.some((p) => p.question_count === 0 && !p.extraction_error) ? 3000 : false,
  });
  const subjects = useQuery({ queryKey: ["subjects"], queryFn: listSubjects });

  const [subjectId, setSubjectId] = useState("");
  const [duration, setDuration] = useState("");
  const [paper, setPaper] = useState<File | null>(null);
  const [markScheme, setMarkScheme] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);

  const hide = useMutation({
    mutationFn: hidePastPaper,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["past-papers"] }),
    onError: (err) => setError(err instanceof ApiError ? err.message : String(err)),
  });

  const upload = useMutation({
    mutationFn: () =>
      uploadPastPaper({
        subject_id: Number(subjectId),
        paper: paper!,
        mark_scheme: markScheme,
        duration_minutes: duration ? Number(duration) : null,
      }),
    onSuccess: () => {
      setDuration("");
      setPaper(null);
      setMarkScheme(null);
      queryClient.invalidateQueries({ queryKey: ["past-papers"] });
    },
    onError: (err) => setError(err instanceof ApiError ? err.message : String(err)),
  });

  // The mark scheme is deliberately not part of this: a paper without one still
  // uploads and still gets marked — it just auto-finalizes nothing, which the
  // copy below the file inputs says in the tutor's own terms.
  const ready = subjectId && paper;

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (ready) upload.mutate();
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold text-slate-800">Past papers</h2>
        <p className="text-sm text-slate-500">
          Upload a full paper once and every student taking that subject can sit it. Their answers
          are marked question by question, feeding both topic mastery and their past-paper score.
        </p>
      </div>

      <form onSubmit={onSubmit} className="space-y-3 rounded-lg border bg-white p-4">
        <h3 className="font-medium text-slate-800">Add a paper</h3>
        <p className="text-xs text-ink-500">
          The AI reads the session, paper number and question list off the paper itself once it's
          uploaded — there's nothing to type here but the subject and files.
        </p>
        <div className="grid gap-3 sm:grid-cols-2">
          <select
            value={subjectId}
            onChange={(e) => setSubjectId(e.target.value)}
            className="rounded border border-slate-300 px-2 py-1.5 text-sm"
          >
            <option value="">Subject…</option>
            {subjects.data?.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name} ({s.exam_board})
              </option>
            ))}
          </select>
          <input
            type="number"
            value={duration}
            onChange={(e) => setDuration(e.target.value)}
            placeholder="Time allowed (minutes)"
            className="rounded border border-slate-300 px-2 py-1.5 text-sm"
          />
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          <label className="text-sm text-slate-600">
            Question paper
            <input
              type="file"
              accept="application/pdf,image/*"
              onChange={(e) => setPaper(e.target.files?.[0] ?? null)}
              className="mt-1 block w-full text-sm"
            />
          </label>
          <label className="text-sm text-slate-600">
            Official mark scheme <span className="text-ink-500">(optional)</span>
            <input
              type="file"
              accept="application/pdf,image/*"
              onChange={(e) => setMarkScheme(e.target.files?.[0] ?? null)}
              className="mt-1 block w-full text-sm"
            />
          </label>
        </div>
        <p className="text-xs text-ink-500">
          {markScheme
            ? "Marks that match the scheme and read clearly are finalized for you; the rest come to you to check."
            : "Without the official mark scheme, no mark is finalized for you — every one comes to you to check before it counts."}{" "}
          Students can open the question paper but never the mark scheme.
        </p>

        {error && <p className="text-sm text-red-600">{error}</p>}
        <button
          type="submit"
          disabled={!ready || upload.isPending}
          className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
        >
          {upload.isPending ? "Uploading…" : "Add past paper"}
        </button>
      </form>

      <div className="rounded-lg border bg-white p-4">
        <h3 className="font-medium text-slate-800">Your papers</h3>
        <ul className="mt-2 divide-y text-sm">
          {papers.data?.map((p) => (
            <li key={p.id} className="py-3">
              <div className="flex items-start justify-between">
                <div>
                  <div className="font-medium text-slate-800">{p.display_title}</div>
                  <div className="text-ink-500" aria-live="polite">
                    {statusLine(p)}
                    {p.duration_minutes ? ` · ${p.duration_minutes} min` : ""}
                  </div>
                </div>
                <div className="flex gap-3 text-xs">
                  <AuthFileLink path={pastPaperPaperPath(p.id)} label="Paper" />
                  {/* A paper may have no scheme now that one is optional, and
                      that endpoint 404s. `mark_scheme_name` is the only signal
                      of whether a file exists, and it is tutor-only. */}
                  {p.mark_scheme_name ? (
                    <AuthFileLink path={pastPaperMarkSchemePath(p.id)} label="Mark scheme" />
                  ) : (
                    <span className="text-ink-500">No mark scheme</span>
                  )}
                  {/* A flag, not a deletion — the row carries attempts, marks
                      and the evidence those produced (`PROD-5`), so the copy
                      says what actually happens rather than "delete". */}
                  <button
                    onClick={() => {
                      if (
                        window.confirm(
                          `Take "${p.display_title}" off your list? Students keep it — anyone who has sat it, or is sitting it now, is unaffected.`,
                        )
                      ) {
                        setError(null);
                        hide.mutate(p.id);
                      }
                    }}
                    disabled={hide.isPending}
                    className="text-red-600 hover:underline disabled:opacity-50"
                  >
                    Remove
                  </button>
                </div>
              </div>
            </li>
          ))}
          {papers.data?.length === 0 && (
            <li className="py-2 text-slate-500">No past papers yet.</li>
          )}
        </ul>
      </div>
    </div>
  );
}
