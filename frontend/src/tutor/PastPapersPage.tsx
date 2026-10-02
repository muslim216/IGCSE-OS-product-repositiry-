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
import { Button, Field, FileInput, Input, Select } from "../components/controls";
import { ConfirmDialog, ErrorState, PageHeader, SectionSkeleton } from "../components/page";
import { EmptyState, SectionCard, SectionHeader } from "../components/ui";
import { friendlyError } from "../lib/errors";
import { formatDuration } from "../lib/schedule";

type PaperRow = NonNullable<Awaited<ReturnType<typeof listPastPapers>>>[number];

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

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
 * students keep it (`hide_past_paper`) — and the API offers no way to re-run a
 * past paper's extraction. That advice left the unreadable paper on every
 * student's list beside its replacement while telling the tutor it was gone.
 */
function statusLine(p: PaperRow): string {
  if (p.extraction_error)
    return "Couldn't read this paper. Upload a clearer copy — a clean PDF works best. Students still see this one; removing it only takes it off your list.";
  if (p.question_count > 0) {
    const marks = p.total_marks ? ` · ${p.total_marks} marks` : "";
    return `${plural(p.question_count, "question", "questions")}${marks}`;
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
  // Bumped after an upload so both pickers remount: clearing the files alone
  // would leave them still naming what was just sent.
  const [pickerKey, setPickerKey] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [hiding, setHiding] = useState<PaperRow | null>(null);

  const hide = useMutation({
    mutationFn: hidePastPaper,
    onSuccess: () => {
      setHiding(null);
      queryClient.invalidateQueries({ queryKey: ["past-papers"] });
    },
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
    <div>
      <PageHeader
        title="Past papers"
        description="Upload a full paper once and every student taking that subject can sit it. Their answers are marked question by question, feeding both topic mastery and their past-paper score."
        back={{ to: "/tutor/library", label: "Library" }}
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
            ) : papers.data?.length === 0 ? (
              <EmptyState
                title="No past papers yet."
                hint="Add one above and it's ready for your students as soon as the questions are read."
              />
            ) : (
              <ul className="divide-y divide-line text-sm">
                {papers.data?.map((p) => (
                  <li key={p.id} className="py-3">
                    <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
                      <div className="min-w-0">
                        <p className="font-medium text-ink-900">{p.display_title}</p>
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
                          <details className="mt-1 text-xs text-ink-500">
                            <summary className="cursor-pointer">What went wrong</summary>
                            <p className="mt-1">{p.extraction_error}</p>
                          </details>
                        )}
                      </div>
                      <div className="flex flex-wrap items-center gap-4 text-sm">
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
                          aria-label={`Remove ${p.display_title}`}
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
            <p>
              <span className="font-medium text-ink-900">{hiding?.display_title}</span> will no
              longer appear here. Students keep it — anyone who has sat it, or is sitting it now, is
              unaffected.
            </p>
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
    </div>
  );
}
