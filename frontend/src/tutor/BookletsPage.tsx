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
import { ArrowDown, ArrowUp, Plus } from "lucide-react";
import { AuthFileLink } from "../components/AuthFile";
import { Button, Field, FileInput, inputClasses, Select } from "../components/controls";
import { ErrorState, PageHeader, SectionSkeleton } from "../components/page";
import { EmptyState, Reveal, SectionCard, SectionHeader } from "../components/ui";
import { friendlyError } from "../lib/errors";

/** Whatever the job is doing right now, said once, in the tutor's terms.
 *
 * `paper_count` is deliberately not rendered until there are papers: a booklet
 * mid-read has none yet, and "0 papers" would be a measurement we have not
 * taken presented as one we have (`PROD-2`, `UX-19`).
 *
 * A failure's own text is the job's raw exception, so it is not the status
 * line: the line says what happened, and the reason sits behind "What went
 * wrong" beside the retry.
 */
function statusLine(b: Booklet): string {
  switch (b.status) {
    case "extracting":
      return "Reading the list of papers out of this booklet…";
    case "extraction_failed":
      return "Couldn't read this booklet. Try again, or upload a clearer PDF.";
    case "review":
      return "Ready for you to check.";
    case "applying":
      return "Cutting the papers out now…";
    case "applied":
      return b.paper_count > 0
        ? `Done — cut into ${b.paper_count} ${b.paper_count === 1 ? "paper" : "papers"}.`
        : "Done.";
    default: {
      // A status added to the API before this screen knows it: readable, never
      // the raw enum.
      const words = b.status.replace(/_/g, " ");
      return words.charAt(0).toUpperCase() + words.slice(1);
    }
  }
}

const BLANK: DraftPaper = {
  title: "",
  session_label: "",
  paper_number: "",
  first_page: 1,
  last_page: 1,
};

const cell = `${inputClasses} min-w-[6rem]`;

/**
 * The tutor's correction of the AI's list, then their approval of it.
 *
 * Keyed by booklet id at the call site so the draft is seeded once, from the
 * server's copy, and never re-seeded underneath someone mid-edit. The draft is
 * the one thing here that is legitimately local: it is an unsaved form, not
 * server state copied into `useState` (`FE-6`).
 */
type Row = { key: number; paper: DraftPaper };

let nextRowKey = 0;
const asRow = (paper: DraftPaper): Row => ({ key: nextRowKey++, paper });

function DraftEditor({ booklet }: Readonly<{ booklet: BookletDetail }>) {
  const queryClient = useQueryClient();
  // Each row carries its own key, because a row's identity is not its position:
  // rows are added, removed and reordered. The values survive an index key
  // either way — the inputs are controlled — but the DOM state React does not
  // own does not: focus and the caret jump to whatever now sits at that index,
  // so a tutor who reorders while typing keeps typing into a different paper.
  const [rows, setRows] = useState<Row[]>(() => (booklet.draft?.papers ?? []).map(asRow));
  const papers = rows.map((r) => r.paper);
  const [error, setError] = useState<string | null>(null);

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["booklets"] });
    queryClient.invalidateQueries({ queryKey: ["booklet", booklet.id] });
  };
  const onError = (err: unknown) => setError(friendlyError(err, "That didn't save. Try again."));

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
    setRows((current) =>
      current.map((r, n) => (n === i ? { ...r, paper: { ...r.paper, ...patch } } : r)),
    );

  const move = (i: number, by: number) =>
    setRows((current) => {
      const to = i + by;
      if (to < 0 || to >= current.length) return current;
      const next = [...current];
      [next[i], next[to]] = [next[to], next[i]];
      return next;
    });

  const mismatch = booklet.draft?.scheme_mismatch;

  return (
    <div className="space-y-4 rounded-xl border border-line bg-canvas p-4">
      <div>
        <h3 className="font-medium text-ink-900">Check the papers in {booklet.display_title}</h3>
        <p className="mt-1 text-sm text-ink-500">
          This is what the AI read off the booklet. Change anything that is wrong, add a paper it
          missed, drop one it invented — your list is the one that gets cut.
        </p>
      </div>

      {mismatch && (
        <div role="alert" className="rounded-lg bg-risk-100 p-3 text-sm text-ink-900">
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
              <tr className="text-left text-xs font-medium text-ink-500">
                <th className="pb-2 pr-2 font-medium">Title</th>
                <th className="pb-2 pr-2 font-medium">Session</th>
                <th className="pb-2 pr-2 font-medium">Paper number</th>
                <th className="pb-2 pr-2 font-medium">First page</th>
                <th className="pb-2 pr-2 font-medium">Last page</th>
                <th className="pb-2">
                  <span className="sr-only">Order and remove</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map(({ key, paper: p }, i) => (
                <tr key={key} className="border-t border-line align-middle">
                  <td className="py-2 pr-2">
                    <input
                      aria-label={`Title, paper ${i + 1}`}
                      value={p.title}
                      onChange={(e) => edit(i, { title: e.target.value })}
                      className={cell}
                    />
                  </td>
                  <td className="py-2 pr-2">
                    <input
                      aria-label={`Session, paper ${i + 1}`}
                      value={p.session_label}
                      onChange={(e) => edit(i, { session_label: e.target.value })}
                      className={cell}
                    />
                  </td>
                  <td className="py-2 pr-2">
                    <input
                      aria-label={`Paper number, paper ${i + 1}`}
                      value={p.paper_number}
                      onChange={(e) => edit(i, { paper_number: e.target.value })}
                      className={cell}
                    />
                  </td>
                  <td className="py-2 pr-2">
                    <input
                      type="number"
                      aria-label={`First page, paper ${i + 1}`}
                      value={p.first_page}
                      onChange={(e) => edit(i, { first_page: Number(e.target.value) })}
                      className={`${cell} tabular-nums`}
                    />
                  </td>
                  <td className="py-2 pr-2">
                    <input
                      type="number"
                      aria-label={`Last page, paper ${i + 1}`}
                      value={p.last_page}
                      onChange={(e) => edit(i, { last_page: Number(e.target.value) })}
                      className={`${cell} tabular-nums`}
                    />
                  </td>
                  <td className="whitespace-nowrap py-2">
                    <span className="flex items-center gap-0.5">
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => move(i, -1)}
                        disabled={i === 0}
                        aria-label={`Move paper ${i + 1} up`}
                      >
                        <ArrowUp aria-hidden className="h-4 w-4" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => move(i, 1)}
                        disabled={i === papers.length - 1}
                        aria-label={`Move paper ${i + 1} down`}
                      >
                        <ArrowDown aria-hidden className="h-4 w-4" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => setRows((current) => current.filter((_, n) => n !== i))}
                        aria-label={`Remove paper ${i + 1}`}
                      >
                        Remove
                      </Button>
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {error && (
        <p role="alert" className="text-sm text-risk-600">
          {error}
        </p>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <Button
          variant="ghost"
          onClick={() => setRows((current) => [...current, asRow({ ...BLANK })])}
        >
          <Plus aria-hidden className="h-4 w-4" />
          Add a paper
        </Button>
        <span className="flex-1" />
        <Button
          variant="secondary"
          onClick={() => {
            setError(null);
            save.mutate();
          }}
          loading={save.isPending}
        >
          Save changes
        </Button>
        <Button
          onClick={() => {
            setError(null);
            approve.mutate();
          }}
          loading={approve.isPending}
          disabled={save.isPending || papers.length === 0}
        >
          Approve and cut the papers
        </Button>
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
  // Bumped after an upload so both pickers remount: clearing the files alone
  // would leave them still naming what was just sent.
  const [pickerKey, setPickerKey] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const upload = useMutation({
    mutationFn: () =>
      uploadBooklet({ subject_id: Number(subjectId), file: file!, mark_scheme: markScheme }),
    onSuccess: () => {
      setFile(null);
      setMarkScheme(null);
      setPickerKey((k) => k + 1);
      queryClient.invalidateQueries({ queryKey: ["booklets"] });
    },
    onError: (err) => setError(friendlyError(err, "That booklet didn't upload. Try again.")),
  });

  // Its failure is shown on the booklet it was for, not in the upload form.
  const retry = useMutation({
    mutationFn: retryBookletExtraction,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["booklets"] }),
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
    <div>
      <PageHeader
        title="Booklets"
        description="One PDF holding several whole past papers. The AI reads out what is inside, you check the list, and each paper is cut into its own past paper for students to sit."
        back={{ to: "/tutor/library", label: "Library" }}
      />

      <div className="space-y-6">
        <SectionCard>
          <form onSubmit={onSubmit} className="space-y-4">
            <SectionHeader
              title="Add a booklet"
              description="A booklet must be a PDF — the papers are cut out of it by page. A single paper, or a photo of one, goes on the Past papers page instead."
            />
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Subject">
                <Select value={subjectId} onChange={(e) => setSubjectId(e.target.value)}>
                  <option value="">Choose a subject</option>
                  {subjects.data?.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.name} ({s.exam_board})
                    </option>
                  ))}
                </Select>
              </Field>
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Booklet">
                <FileInput
                  key={`booklet-${pickerKey}`}
                  accept="application/pdf"
                  prompt="Choose the booklet"
                  hint="PDF only"
                  onFiles={(files) => setFile(files[0] ?? null)}
                />
              </Field>
              <Field label="Mark schemes" optional>
                <FileInput
                  key={`schemes-${pickerKey}`}
                  accept="application/pdf"
                  prompt="Choose the mark schemes"
                  hint="PDF only"
                  onFiles={(files) => setMarkScheme(files[0] ?? null)}
                />
              </Field>
            </div>
            <p className="text-sm text-ink-500">
              {markScheme
                ? "The schemes are read too, and checked against the paper list — you're told if the two disagree."
                : "Without the mark schemes, no mark is finalized for you — every one comes to you to check before it counts, and nothing double-checks where one paper ends and the next begins."}{" "}
              Students can open the booklet but never the mark schemes.
            </p>

            {error && (
              <p role="alert" className="text-sm text-risk-600">
                {error}
              </p>
            )}
            <Button type="submit" disabled={!ready} loading={upload.isPending}>
              Add booklet
            </Button>
          </form>
        </SectionCard>

        <SectionCard>
          <SectionHeader title="Your booklets" />
          <div className="mt-3">
            {booklets.isLoading ? (
              <SectionSkeleton rows={3} label="Loading your booklets" />
            ) : booklets.isError ? (
              <ErrorState error={booklets.error} onRetry={() => booklets.refetch()} />
            ) : rows.length === 0 ? (
              <EmptyState
                title="No booklets yet."
                hint="Add one above and the AI starts reading it straight away."
              />
            ) : (
              <ul className="divide-y divide-line text-sm">
                {rows.map((b) => (
                  <li key={b.id} className="py-3">
                    <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
                      <div className="min-w-0">
                        <p className="font-medium text-ink-900">{b.display_title}</p>
                        <p
                          className={
                            b.status === "extraction_failed" ? "text-risk-600" : "text-ink-500"
                          }
                          aria-live="polite"
                        >
                          {statusLine(b)}
                        </p>
                        {b.status === "extraction_failed" && b.error && (
                          <details className="mt-1 text-xs text-ink-500">
                            <summary className="cursor-pointer">What went wrong</summary>
                            <p className="mt-1">{b.error}</p>
                          </details>
                        )}
                        {retry.isError && retry.variables === b.id && (
                          <p role="alert" className="mt-1 text-risk-600">
                            {friendlyError(retry.error, "That didn't start. Try again.")}
                          </p>
                        )}
                      </div>
                      <div className="flex flex-wrap items-center gap-4 text-sm">
                        {b.status === "review" && (
                          <Button
                            variant={openId === b.id ? "ghost" : "secondary"}
                            size="sm"
                            aria-expanded={openId === b.id}
                            onClick={() => setOpenId(openId === b.id ? null : b.id)}
                          >
                            {openId === b.id ? "Close" : "Check the papers"}
                          </Button>
                        )}
                        {b.status === "extraction_failed" && (
                          <Button
                            variant="secondary"
                            size="sm"
                            onClick={() => retry.mutate(b.id)}
                            loading={retry.isPending && retry.variables === b.id}
                            disabled={retry.isPending}
                          >
                            Try again
                          </Button>
                        )}
                        <AuthFileLink path={bookletFilePath(b.id)} label="Booklet" />
                        {b.mark_scheme_name ? (
                          <AuthFileLink path={bookletMarkSchemePath(b.id)} label="Mark schemes" />
                        ) : (
                          <span className="text-ink-500">No mark schemes</span>
                        )}
                      </div>
                    </div>
                    <Reveal open={openId === b.id} className="pt-3">
                      {openId === b.id && (
                        <>
                          {detail.isLoading ? (
                            <SectionSkeleton rows={4} label="Loading the papers" />
                          ) : detail.isError ? (
                            <ErrorState error={detail.error} onRetry={() => detail.refetch()} />
                          ) : (
                            detail.data?.id === b.id && (
                              <DraftEditor key={b.id} booklet={detail.data} />
                            )
                          )}
                        </>
                      )}
                    </Reveal>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </SectionCard>
      </div>
    </div>
  );
}
