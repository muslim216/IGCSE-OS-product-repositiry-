import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import { useLocation } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  getPastPaper,
  hidePastPaper,
  listPastPapers,
  pastPaperPaperPath,
  pastPaperMarkSchemePath,
  replacePastPaper,
  retryPastPaper,
  uploadPastPaper,
} from "../api/pastPapers";
import { listSubjects } from "../api/groups";
import { AuthFileLink } from "../components/AuthFile";
import { Button, Field, FileInput, Input, Select } from "../components/controls";
import { ConfirmDialog, ErrorState, PageHeader, SectionSkeleton } from "../components/page";
import { EmptyState, Modal, Reveal, SectionCard, SectionHeader } from "../components/ui";
import { friendlyError } from "../lib/errors";
import { formatDuration } from "../lib/schedule";

type PaperRow = NonNullable<Awaited<ReturnType<typeof listPastPapers>>>[number];

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

/** What a paper is called to the tutor. Until the AI has read it a paper has
 *  no name, and several "Untitled paper" rows name none of them — the file is
 *  what the tutor uploaded and will recognise. */
const nameOf = (p: PaperRow) => (p.title === null && p.paper_name ? p.paper_name : p.display_title);

/** The one status line a paper gets — never two.
 *
 * Written as early returns rather than nested ternaries because the ordering
 * *is* the rule: a failed paper keeps the name "Untitled paper" and a question
 * count of zero, since the AI reads the name and the questions in the same pass
 * and failing loses both. Those are the same two signals the in-progress state
 * has, so a shape that can evaluate more than one branch tells a tutor it is
 * still working when it has already given up — which it did, until this was a
 * single exclusive branch.
 *
 * The failure's own text is the job's raw exception, so it is not the status
 * line: the line says what happened and what to do, and the raw reason sits
 * behind "What went wrong" for anyone who needs it.
 *
 * "What to do" is only what the tutor can actually do. It once said "Remove it
 * and upload it again", but Remove hides a paper from this list alone —
 * students keep it (`hide_past_paper`) — so that advice left the unreadable
 * paper on every student's list beside its replacement while telling the tutor
 * it was gone. The fix is on the paper itself now (owner decision, 2026-10-02):
 * read it again, or swap in a clearer copy, and either way students keep the
 * one paper they already have.
 */
function statusLine(p: PaperRow): string {
  if (p.extraction_error)
    return "Couldn't read this paper. Try again, or upload a clearer copy — a clean PDF works best.";
  if (p.question_count > 0) {
    const marks = p.total_marks ? ` · ${p.total_marks} marks` : "";
    return `${plural(p.question_count, "question", "questions")}${marks}`;
  }
  return "Reading the questions out of the paper…";
}

/** A read paper's questions, and the topics each one's marks count towards.
 *
 * A past-paper mark feeds the student's topic scores through these tags (owner
 * decision, 2026-10-02), so the tutor sees what each mark counts towards — and
 * which count towards none (`PROD-1`). Fetched only when opened: the list above
 * polls while any paper is being read, and a detail request for every row on
 * every poll would be spent on panels nobody opened.
 */
function PaperQuestions({ paperId, name }: { paperId: number; name: string }) {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const detail = useQuery({
    queryKey: ["past-paper", paperId],
    queryFn: () => getPastPaper(paperId),
    enabled: open,
  });
  const untagged = detail.data?.questions.filter((q) => q.topics.length === 0).length ?? 0;

  return (
    <div className="mt-1 text-xs text-ink-500">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((o) => !o)}
        className="font-medium text-brand-600 hover:text-brand-700"
      >
        {/* One name whatever the state — `aria-expanded` already says which —
            and the paper's, since every read paper has this button. */}
        Questions and topics<span className="sr-only"> for {name}</span>
      </button>
      <Reveal open={open} id={panelId} className="pt-2">
        {open &&
          (detail.isPending ? (
            <SectionSkeleton rows={2} label="Loading the questions" />
          ) : detail.isError ? (
            <ErrorState
              title="The questions didn't load"
              error={detail.error}
              onRetry={() => detail.refetch()}
            />
          ) : (
            <>
              {untagged > 0 && (
                <p className="mb-2 text-warn-700">
                  {plural(untagged, "question isn't", "questions aren't")} linked to a topic, so{" "}
                  {untagged === 1 ? "its marks count" : "their marks count"} towards no topic score.
                </p>
              )}
              <ol className="space-y-1">
                {detail.data.questions.map((q) => (
                  <li key={q.id} className="flex flex-wrap gap-x-2">
                    <span className="font-medium text-ink-700">Q{q.number}</span>
                    <span>{plural(q.max_marks, "mark", "marks")}</span>
                    <span>
                      · {q.topics.length > 0 ? q.topics.map((t) => t.title).join(", ") : "No topic"}
                    </span>
                  </li>
                ))}
              </ol>
            </>
          ))}
      </Reveal>
    </div>
  );
}

export default function PastPapersPage() {
  const queryClient = useQueryClient();
  const { hash } = useLocation();
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
  // Bumped after an upload so both pickers remount: clearing the files alone
  // would leave them still naming what was just sent.
  const [pickerKey, setPickerKey] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [hiding, setHiding] = useState<PaperRow | null>(null);
  const [replacing, setReplacing] = useState<PaperRow | null>(null);
  const [copy, setCopy] = useState<File | null>(null);

  // Fixing or removing a paper changes the tutor's to-do list as well as this
  // one: an unreadable paper leaves it once its read is under way, or once it
  // is off the shelf.
  function refreshLists() {
    queryClient.invalidateQueries({ queryKey: ["past-papers"] });
    queryClient.invalidateQueries({ queryKey: ["assignments-attention"] });
  }

  // A fixed paper's row takes the server's answer at once rather than after the
  // refetch: until then the cached row still offered both fixes, and a second
  // press was refused (409) as the paper was already being read.
  function showFixed(updated: PaperRow) {
    queryClient.setQueryData<PaperRow[]>(["past-papers"], (rows) =>
      rows?.map((row) => (row.id === updated.id ? updated : row)),
    );
    refreshLists();
  }

  const hide = useMutation({
    mutationFn: hidePastPaper,
    onSuccess: () => {
      setHiding(null);
      refreshLists();
    },
  });

  const retry = useMutation({
    mutationFn: retryPastPaper,
    onSuccess: showFixed,
    // A refusal usually means the row is out of date — someone else fixed it.
    onError: refreshLists,
  });

  const replace = useMutation({
    mutationFn: ({ id, file }: { id: number; file: File }) => replacePastPaper(id, file),
    onSuccess: (updated) => {
      setReplacing(null);
      setCopy(null);
      showFixed(updated);
    },
    onError: refreshLists,
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
      setPickerKey((k) => k + 1);
      queryClient.invalidateQueries({ queryKey: ["past-papers"] });
    },
    onError: (err) => setError(friendlyError(err, "That paper didn't upload. Try again.")),
  });

  // The to-do list links to one paper here (`lib/attention.ts`). It is brought
  // into view and focused once the list has arrived — once per link, not again
  // on every three-second poll while something is being read.
  const arrivedAt = useRef<string | null>(null);
  useEffect(() => {
    if (!hash.startsWith("#paper-") || !papers.data || arrivedAt.current === hash) return;
    const row = document.getElementById(hash.slice(1));
    if (!row) return;
    arrivedAt.current = hash;
    row.scrollIntoView?.({ block: "center" });
    row.focus();
  }, [hash, papers.data]);

  // A paper waiting on a fix leads the list: it is the one row asking something
  // of the tutor. Otherwise newest first, as the API sends them.
  const rows = [...(papers.data ?? [])].sort(
    (a, b) => Number(Boolean(b.extraction_error)) - Number(Boolean(a.extraction_error)),
  );

  // The mark scheme is deliberately not part of this: a paper without one still
  // uploads and still gets marked — it just auto-finalizes nothing, which the
  // copy below the file inputs says in the tutor's own terms.
  const ready = subjectId && paper;

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (ready) upload.mutate();
  }

  function onReplace(e: FormEvent) {
    e.preventDefault();
    if (replacing && copy) replace.mutate({ id: replacing.id, file: copy });
  }

  return (
    <div>
      <PageHeader
        title="Past papers"
        description="Upload a full paper once and every student taking that subject can sit it. Their answers are marked question by question, feeding both topic mastery and their past-paper score."
        back={{ to: "/tutor/papers", label: "Papers & mocks" }}
      />

      <div className="space-y-6">
        <SectionCard>
          <form onSubmit={onSubmit} className="space-y-4">
            <SectionHeader
              title="Add a paper"
              description="The AI reads the session, paper number and questions off the paper itself — all you choose is the subject and the files."
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
              <Field label="Time allowed, in minutes" optional>
                <Input
                  type="number"
                  min={1}
                  inputMode="numeric"
                  value={duration}
                  onChange={(e) => setDuration(e.target.value)}
                  placeholder="e.g. 90"
                />
              </Field>
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Question paper">
                <FileInput
                  key={`paper-${pickerKey}`}
                  accept="application/pdf,image/*"
                  prompt="Choose the question paper"
                  hint="PDF or photo"
                  onFiles={(files) => setPaper(files[0] ?? null)}
                />
              </Field>
              <Field label="Official mark scheme" optional>
                <FileInput
                  key={`scheme-${pickerKey}`}
                  accept="application/pdf,image/*"
                  prompt="Choose the mark scheme"
                  hint="PDF or photo"
                  onFiles={(files) => setMarkScheme(files[0] ?? null)}
                />
              </Field>
            </div>
            <p className="text-sm text-ink-500">
              {markScheme
                ? "Marks that match the scheme and read clearly are finalized for you; the rest come to you to check."
                : "Without the official mark scheme, no mark is finalized for you — every one comes to you to check before it counts."}{" "}
              Students can open the question paper but never the mark scheme.
            </p>

            {error && (
              <p role="alert" className="text-sm text-risk-600">
                {error}
              </p>
            )}
            <Button type="submit" disabled={!ready} loading={upload.isPending}>
              Add past paper
            </Button>
          </form>
        </SectionCard>

        <SectionCard>
          <SectionHeader title="Your papers" />
          <div className="mt-3">
            {papers.isLoading ? (
              <SectionSkeleton rows={3} label="Loading your papers" />
            ) : papers.isError ? (
              <ErrorState error={papers.error} onRetry={() => papers.refetch()} />
            ) : rows.length === 0 ? (
              <EmptyState
                title="No past papers yet."
                hint="Add one above and it's ready for your students as soon as the questions are read."
              />
            ) : (
              <ul className="divide-y divide-line text-sm">
                {rows.map((p) => (
                  <li
                    key={p.id}
                    id={`paper-${p.id}`}
                    tabIndex={-1}
                    className="scroll-mt-24 rounded-sm py-3 focus:outline focus:outline-2 focus:outline-offset-4 focus:outline-brand-600"
                  >
                    <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
                      <div className="min-w-0">
                        <p className="font-medium text-ink-900">{p.display_title}</p>
                        {/* The file names an unread paper (`nameOf`). */}
                        {p.title === null && p.paper_name && (
                          <p className="text-xs text-ink-500">{p.paper_name}</p>
                        )}
                        <p
                          className={p.extraction_error ? "text-risk-600" : "text-ink-500"}
                          aria-live="polite"
                        >
                          {statusLine(p)}
                          {p.duration_minutes && !p.extraction_error
                            ? ` · ${formatDuration(p.duration_minutes)} allowed`
                            : ""}
                        </p>
                        {p.extraction_error && (
                          <>
                            <p className="text-ink-500">
                              Students still see this one. Anything they send for it is marked once
                              it's read.
                            </p>
                            <details className="mt-1 text-xs text-ink-500">
                              <summary className="cursor-pointer">What went wrong</summary>
                              <p className="mt-1">{p.extraction_error}</p>
                            </details>
                            {retry.isError && retry.variables === p.id && (
                              <p role="alert" className="mt-1 text-risk-600">
                                {friendlyError(retry.error, "That didn't start. Try again.")}
                              </p>
                            )}
                          </>
                        )}
                        {p.question_count > 0 && (
                          <PaperQuestions paperId={p.id} name={p.display_title} />
                        )}
                      </div>
                      <div className="flex flex-wrap items-center gap-4 text-sm">
                        {p.extraction_error && (
                          <>
                            {/* Which paper rides along for screen readers, after
                                the visible words so the spoken name still starts
                                with what is on the button (WCAG 2.5.3). */}
                            <Button
                              variant="secondary"
                              size="sm"
                              loading={retry.isPending && retry.variables === p.id}
                              onClick={() => retry.mutate(p.id)}
                            >
                              Try again
                              <span className="sr-only"> to read {nameOf(p)}</span>
                            </Button>
                            <Button
                              variant="secondary"
                              size="sm"
                              // One fix at a time: once Try again is under way
                              // the paper is being read, and a replacement
                              // would be refused.
                              disabled={retry.isPending && retry.variables === p.id}
                              onClick={() => {
                                replace.reset();
                                setCopy(null);
                                setReplacing(p);
                              }}
                            >
                              Upload a clearer copy
                              <span className="sr-only"> of {nameOf(p)}</span>
                            </Button>
                          </>
                        )}
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
                        <Button
                          variant="ghost"
                          size="sm"
                          aria-label={`Remove ${nameOf(p)}`}
                          onClick={() => {
                            hide.reset();
                            setHiding(p);
                          }}
                        >
                          Remove
                        </Button>
                      </div>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </SectionCard>
      </div>

      <ConfirmDialog
        open={hiding !== null}
        title="Take this paper off your list?"
        body={
          <>
            {hiding?.extraction_error ? (
              // Not "unaffected": an unread paper cannot be marked, so whatever
              // students send for it waits until someone fixes it — and once it
              // is off this list, nobody will.
              <p>
                <span className="font-medium text-ink-900">{nameOf(hiding)}</span> will no longer
                appear here, but students keep it, and nothing they send for it can be marked until
                it's read. Trying again or uploading a clearer copy fixes it for them.
              </p>
            ) : (
              <p>
                <span className="font-medium text-ink-900">{hiding?.display_title}</span> will no
                longer appear here. Students keep it — anyone who has sat it, or is sitting it now,
                is unaffected.
              </p>
            )}
            {hide.isError && (
              <p role="alert" className="mt-3 text-risk-600">
                {friendlyError(hide.error, "That didn't work. Try again.")}
              </p>
            )}
          </>
        }
        confirmLabel="Take it off my list"
        busy={hide.isPending}
        onConfirm={() => hiding && hide.mutate(hiding.id)}
        onCancel={() => setHiding(null)}
      />

      <Modal
        open={replacing !== null}
        // Not closable mid-upload: closing would not cancel the request, and the
        // dialog is where its outcome is reported.
        onClose={() => {
          if (!replace.isPending) setReplacing(null);
        }}
        title="Upload a clearer copy"
      >
        <form onSubmit={onReplace}>
          <p className="text-sm text-ink-500">
            It replaces{" "}
            <span className="font-medium text-ink-900">{replacing && nameOf(replacing)}</span> and
            is read straight away. Use a copy of the same paper: students keep it, and any answers
            they've sent are marked against it.
          </p>
          <Field label="Question paper" className="mt-4">
            <FileInput
              accept="application/pdf,image/*"
              prompt="Choose the clearer copy"
              hint="PDF or photo"
              onFiles={(files) => setCopy(files[0] ?? null)}
            />
          </Field>
          {replace.isError && (
            <p role="alert" className="mt-3 text-sm text-risk-600">
              {friendlyError(replace.error, "That copy didn't upload. Try again.")}
            </p>
          )}
          <div className="mt-6 flex justify-end gap-2">
            <Button variant="ghost" disabled={replace.isPending} onClick={() => setReplacing(null)}>
              Cancel
            </Button>
            <Button type="submit" disabled={!copy} loading={replace.isPending}>
              Upload and read it
            </Button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
