import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  approveBooklet,
  bookletFilePath,
  bookletMarkSchemePath,
  getBooklet,
  listBooklets,
  retryBookletExtraction,
  saveBookletDraft,
  uploadBooklet,
  type Booklet,
  type BookletDetail,
  type DraftPaper,
} from "../api/booklets";
import { listSubjects } from "../api/groups";
import { AuthFileLink } from "../components/AuthFile";
import { ApiError } from "../api/client";

/** Whatever the job is doing right now, said once, in the tutor's terms.
 *
 * `paper_count` is deliberately not rendered until there are papers: a booklet
 * mid-read has none yet, and "0 papers" would be a measurement we have not
 * taken presented as one we have (`PROD-2`, `UX-19`).
 */
function statusLine(b: Booklet): string {
  switch (b.status) {
    case "extracting":
      return "Reading the list of papers out of this booklet…";
    case "extraction_failed":
      return b.error ? `Couldn't read this booklet: ${b.error}` : "Couldn't read this booklet.";
    case "review":
      return "Ready for you to check.";
    case "applying":
      return "Cutting the papers out now…";
    case "applied":
      return b.paper_count > 0 ? `Done — ${b.paper_count} papers.` : "Done.";
    default:
      return b.status;
  }
}

const BLANK: DraftPaper = {
  title: "",
  session_label: "",
  paper_number: "",
  first_page: 1,
  last_page: 1,
};

const cell = "w-full rounded border border-line bg-surface px-2 py-1 text-sm text-ink-900";

/**
 * The tutor's correction of the AI's list, then their approval of it.
 *
 * Keyed by booklet id at the call site so the draft is seeded once, from the
 * server's copy, and never re-seeded underneath someone mid-edit. The draft is
 * the one thing here that is legitimately local: it is an unsaved form, not
 * server state copied into `useState` (`FE-6`).
 */
function DraftEditor({ booklet }: { booklet: BookletDetail }) {
  const queryClient = useQueryClient();
  const [papers, setPapers] = useState<DraftPaper[]>(booklet.draft?.papers ?? []);
  const [error, setError] = useState<string | null>(null);

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["booklets"] });
    queryClient.invalidateQueries({ queryKey: ["booklet", booklet.id] });
  };
  const onError = (err: unknown) => setError(err instanceof ApiError ? err.message : String(err));

  const save = useMutation({
    mutationFn: () =>
      saveBookletDraft(booklet.id, {
        papers,
        // Carried back untouched — they are the AI's reading of the mark
        // scheme, and dropping them would erase the mismatch warning.
        scheme_papers: booklet.draft?.scheme_papers ?? null,
        scheme_mismatch: booklet.draft?.scheme_mismatch ?? null,
      }),
    onSuccess: invalidate,
    onError,
  });

  const approve = useMutation({
    mutationFn: () => approveBooklet(booklet.id),
    onSuccess: invalidate,
    onError,
  });

  const edit = (i: number, patch: Partial<DraftPaper>) =>
    setPapers((rows) => rows.map((r, n) => (n === i ? { ...r, ...patch } : r)));

  const move = (i: number, by: number) =>
    setPapers((rows) => {
      const to = i + by;
      if (to < 0 || to >= rows.length) return rows;
      const next = [...rows];
      [next[i], next[to]] = [next[to], next[i]];
      return next;
    });

  const mismatch = booklet.draft?.scheme_mismatch;

  return (
    <div className="space-y-3 rounded-lg border border-line bg-surface p-4">
      <h3 className="font-medium text-ink-900">Check the papers in {booklet.display_title}</h3>
      <p className="text-sm text-ink-500">
        This is what the AI read off the booklet. Change anything that is wrong, add a paper it
        missed, drop one it invented — your list is the one that gets cut.
      </p>

      {mismatch && (
        <div
          role="alert"
          className="rounded-md border border-risk-600 bg-risk-100 p-3 text-sm text-ink-900"
        >
          <strong className="block font-semibold">
            The mark scheme doesn&apos;t agree with the question paper
          </strong>
          <span className="mt-1 block">{mismatch}</span>
          <span className="mt-1 block text-ink-700">
            You decide which is right. Fix the list below if the mark scheme is correct, or approve
            it as it stands if it isn&apos;t.
          </span>
        </div>
      )}

      {papers.length === 0 ? (
        <p className="text-sm text-ink-500">
          No papers in this list yet — add one below to say what is in the booklet.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs uppercase tracking-wider text-ink-500">
                <th className="py-1 pr-2">Title</th>
                <th className="py-1 pr-2">Session</th>
                <th className="py-1 pr-2">Paper</th>
                <th className="py-1 pr-2">First page</th>
                <th className="py-1 pr-2">Last page</th>
                <th className="py-1" />
              </tr>
            </thead>
            <tbody>
              {papers.map((p, i) => (
                <tr key={i} className="border-t border-line align-top">
                  <td className="py-1 pr-2">
                    <input
                      aria-label={`Title, paper ${i + 1}`}
                      value={p.title}
                      onChange={(e) => edit(i, { title: e.target.value })}
                      className={cell}
                    />
                  </td>
                  <td className="py-1 pr-2">
                    <input
                      aria-label={`Session, paper ${i + 1}`}
                      value={p.session_label}
                      onChange={(e) => edit(i, { session_label: e.target.value })}
                      className={cell}
                    />
                  </td>
                  <td className="py-1 pr-2">
                    <input
                      aria-label={`Paper number, paper ${i + 1}`}
                      value={p.paper_number}
                      onChange={(e) => edit(i, { paper_number: e.target.value })}
                      className={cell}
                    />
                  </td>
                  <td className="py-1 pr-2">
                    <input
                      type="number"
                      aria-label={`First page, paper ${i + 1}`}
                      value={p.first_page}
                      onChange={(e) => edit(i, { first_page: Number(e.target.value) })}
                      className={cell}
                    />
                  </td>
                  <td className="py-1 pr-2">
                    <input
                      type="number"
                      aria-label={`Last page, paper ${i + 1}`}
                      value={p.last_page}
                      onChange={(e) => edit(i, { last_page: Number(e.target.value) })}
                      className={cell}
                    />
                  </td>
                  <td className="whitespace-nowrap py-1 text-xs">
                    <button
                      type="button"
                      onClick={() => move(i, -1)}
                      disabled={i === 0}
                      aria-label={`Move paper ${i + 1} up`}
                      className="px-1 text-brand-600 hover:underline disabled:opacity-40"
                    >
                      ↑
                    </button>
                    <button
                      type="button"
                      onClick={() => move(i, 1)}
                      disabled={i === papers.length - 1}
                      aria-label={`Move paper ${i + 1} down`}
                      className="px-1 text-brand-600 hover:underline disabled:opacity-40"
                    >
                      ↓
                    </button>
                    <button
                      type="button"
                      onClick={() => setPapers((rows) => rows.filter((_, n) => n !== i))}
                      aria-label={`Remove paper ${i + 1}`}
                      className="px-1 text-risk-600 hover:underline"
                    >
                      Remove
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {error && <p className="text-sm text-risk-600">{error}</p>}

      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => setPapers((rows) => [...rows, { ...BLANK }])}
          className="rounded-md border border-line-strong px-3 py-2 text-sm text-ink-700"
        >
          Add a paper
        </button>
        <button
          type="button"
          onClick={() => {
            setError(null);
            save.mutate();
          }}
          disabled={save.isPending}
          className="rounded-md border border-line-strong px-3 py-2 text-sm text-ink-700 disabled:opacity-50"
        >
          {save.isPending ? "Saving…" : "Save changes"}
        </button>
        <button
          type="button"
          onClick={() => {
            setError(null);
            approve.mutate();
          }}
          disabled={approve.isPending || papers.length === 0}
          className="rounded-md bg-brand-600 px-4 py-2 text-sm font-medium text-surface hover:bg-brand-700 disabled:opacity-50"
        >
          {approve.isPending ? "Approving…" : "Approve and cut the papers"}
        </button>
      </div>
      <p className="text-xs text-ink-500">
        Save first if you have changed anything — approving cuts the list the server is holding.
      </p>
    </div>
  );
}

export default function BookletsPage() {
  const queryClient = useQueryClient();
  const booklets = useQuery({
    queryKey: ["booklets"],
    queryFn: () => listBooklets(),
    // Both the read and the cut are background jobs, so without this the tutor
    // sits on "Reading…" until they navigate away and back. Self-terminating:
    // once nothing is mid-job the interval returns false.
    refetchInterval: (query) =>
      query.state.data?.some((b) => b.status === "extracting" || b.status === "applying")
        ? 3000
        : false,
  });
  const subjects = useQuery({ queryKey: ["subjects"], queryFn: listSubjects });

  const [openId, setOpenId] = useState<number | null>(null);
  const detail = useQuery({
    queryKey: ["booklet", openId],
    queryFn: () => getBooklet(openId!),
    enabled: openId !== null,
  });

  const [subjectId, setSubjectId] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [markScheme, setMarkScheme] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);

  const upload = useMutation({
    mutationFn: () =>
      uploadBooklet({ subject_id: Number(subjectId), file: file!, mark_scheme: markScheme }),
    onSuccess: () => {
      setFile(null);
      setMarkScheme(null);
      queryClient.invalidateQueries({ queryKey: ["booklets"] });
    },
    onError: (err) => setError(err instanceof ApiError ? err.message : String(err)),
  });

  const retry = useMutation({
    mutationFn: retryBookletExtraction,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["booklets"] }),
    onError: (err) => setError(err instanceof ApiError ? err.message : String(err)),
  });

  const ready = subjectId && file;

  // Newest first, here rather than relying on the server's order — the list is
  // a queue of things the tutor has just uploaded and is waiting on.
  const rows = [...(booklets.data ?? [])].sort((a, b) => b.created_at.localeCompare(a.created_at));

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (ready) upload.mutate();
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="font-display text-xl font-semibold text-ink-900">Booklets</h2>
        <p className="text-sm text-ink-500">
          One PDF holding several whole past papers. The AI reads out what is inside, you check the
          list, and each paper is cut into its own past paper for students to sit.
        </p>
      </div>

      <form onSubmit={onSubmit} className="space-y-3 rounded-lg border border-line bg-surface p-4">
        <h3 className="font-medium text-ink-900">Add a booklet</h3>
        <p className="text-xs text-ink-500">
          A booklet must be a PDF — the papers are cut out of it by page. A single paper, or a photo
          of one, goes on the Past papers page instead.
        </p>
        <div className="grid gap-3 sm:grid-cols-2">
          <select
            value={subjectId}
            onChange={(e) => setSubjectId(e.target.value)}
            className="rounded border border-line-strong bg-surface px-2 py-1.5 text-sm text-ink-900"
          >
            <option value="">Subject…</option>
            {subjects.data?.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name} ({s.exam_board})
              </option>
            ))}
          </select>
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          <label className="text-sm text-ink-700">
            Booklet (PDF)
            <input
              type="file"
              accept="application/pdf"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              className="mt-1 block w-full text-sm"
            />
          </label>
          <label className="text-sm text-ink-700">
            Mark schemes <span className="text-ink-500">(optional)</span>
            <input
              type="file"
              accept="application/pdf"
              onChange={(e) => setMarkScheme(e.target.files?.[0] ?? null)}
              className="mt-1 block w-full text-sm"
            />
          </label>
        </div>
        <p className="text-xs text-ink-500">
          {markScheme
            ? "The schemes are read too, and checked against the paper list — you're told if the two disagree."
            : "Without the mark schemes, no mark is finalized for you — every one comes to you to check before it counts, and nothing double-checks where one paper ends and the next begins."}{" "}
          Students can open the booklet but never the mark schemes.
        </p>

        {error && <p className="text-sm text-risk-600">{error}</p>}
        <button
          type="submit"
          disabled={!ready || upload.isPending}
          className="rounded-md bg-brand-600 px-4 py-2 text-sm font-medium text-surface hover:bg-brand-700 disabled:opacity-50"
        >
          {upload.isPending ? "Uploading…" : "Add booklet"}
        </button>
      </form>

      <div className="rounded-lg border border-line bg-surface p-4">
        <h3 className="font-medium text-ink-900">Your booklets</h3>
        <ul className="mt-2 divide-y divide-line text-sm">
          {rows.map((b) => (
            <li key={b.id} className="py-3">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div>
                  <div className="font-medium text-ink-900">{b.display_title}</div>
                  <div className="text-ink-500" aria-live="polite">
                    {statusLine(b)}
                  </div>
                </div>
                <div className="flex flex-wrap items-center gap-3 text-xs">
                  {b.status === "review" && (
                    <button
                      type="button"
                      onClick={() => setOpenId(openId === b.id ? null : b.id)}
                      className="text-brand-600 hover:underline"
                    >
                      {openId === b.id ? "Close" : "Check the papers"}
                    </button>
                  )}
                  {b.status === "extraction_failed" && (
                    <button
                      type="button"
                      onClick={() => retry.mutate(b.id)}
                      disabled={retry.isPending}
                      className="text-brand-600 hover:underline disabled:opacity-50"
                    >
                      Retry
                    </button>
                  )}
                  <AuthFileLink path={bookletFilePath(b.id)} label="Booklet" />
                  {b.mark_scheme_name ? (
                    <AuthFileLink path={bookletMarkSchemePath(b.id)} label="Mark schemes" />
                  ) : (
                    <span className="text-ink-500">No mark schemes</span>
                  )}
                </div>
              </div>
              {openId === b.id && detail.data?.id === b.id && (
                <div className="mt-3">
                  <DraftEditor key={b.id} booklet={detail.data} />
                </div>
              )}
            </li>
          ))}
          {booklets.data?.length === 0 && <li className="py-2 text-ink-500">No booklets yet.</li>}
        </ul>
      </div>
    </div>
  );
}
