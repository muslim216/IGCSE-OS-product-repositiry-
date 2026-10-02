import { useState, type FormEvent, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ChevronRight, Loader2 } from "lucide-react";
import {
  applySyllabusUpload,
  getSyllabusUpload,
  listSyllabusUploads,
  retrySyllabusExtraction,
  updateSyllabusDraft,
  uploadSyllabus,
  type SubjectLevel,
  type SyllabusChapterDraft,
  type SyllabusDraft,
  type SyllabusTopicDraft,
  type SyllabusUploadDetail,
} from "../api/syllabusUpload";
import { ApiError } from "../api/client";
import { Button, Field, FileInput, Input, inputClasses, Select } from "../components/controls";
import {
  ErrorState,
  NotFoundState,
  PageHeader,
  PageSkeleton,
  SectionSkeleton,
} from "../components/page";
import { EmptyState, SectionCard, SectionHeader } from "../components/ui";
import { friendlyError } from "../lib/errors";

/** Each status as a short chip, and in the words a tutor would use. The tone
 *  carries meaning only alongside the words, never instead of them (UX-15). */
const STATUS: Record<string, { label: string; tone: string }> = {
  extracting: { label: "Reading it now…", tone: "bg-surface-muted text-ink-700" },
  extraction_failed: { label: "Couldn't read it", tone: "bg-risk-100 text-risk-600" },
  review: { label: "Ready for you to check", tone: "bg-warn-100 text-warn-700" },
  applied: { label: "In use", tone: "bg-ok-100 text-ok-700" },
};

function StatusChip({ status }: { status: string }) {
  const known = STATUS[status];
  return (
    <span
      className={`inline-block shrink-0 rounded-md px-2 py-0.5 text-xs font-medium ${known?.tone ?? "bg-surface-muted text-ink-700"}`}
    >
      {known?.label ?? "Status unknown"}
    </span>
  );
}

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

/** The way back from a syllabus to the list. The list and the detail share one
 *  route, so this is a button rather than PageHeader's link — styled the same,
 *  so it reads as the same control it is on every other page. */
function BackButton({ onClick, children }: { onClick: () => void; children: ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="mb-3 inline-flex items-center gap-1 text-sm text-ink-500 transition-colors hover:text-brand-600"
    >
      <ArrowLeft aria-hidden className="h-3.5 w-3.5" />
      {children}
    </button>
  );
}

function UploadForm({ onUploaded }: { onUploaded: (id: number) => void }) {
  const queryClient = useQueryClient();
  const [title, setTitle] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);

  const upload = useMutation({
    mutationFn: () => uploadSyllabus(title || file!.name, file!),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ["syllabus-uploads"] });
      setTitle("");
      setFile(null);
      onUploaded(result.id);
    },
    onError: (err) => setError(friendlyError(err, "That syllabus didn't upload. Try again.")),
  });

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (file) upload.mutate();
  }

  return (
    <SectionCard>
      <form onSubmit={onSubmit} className="space-y-4">
        <SectionHeader
          title="Upload a syllabus"
          description="The AI drafts the chapters and their topics from the exam board's PDF. You check and edit them, then apply it to use the subject with your classes and homework."
        />
        <div className="grid items-start gap-4 sm:grid-cols-2">
          <Field label="Syllabus" hint="The exam board's PDF.">
            <FileInput
              accept="application/pdf"
              prompt="Choose the syllabus PDF"
              onFiles={(files) => setFile(files[0] ?? null)}
            />
          </Field>
          <Field label="Name" optional hint="Leave it blank to use the file's name.">
            <Input
              placeholder="e.g. AQA GCSE Physics 8463"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
            />
          </Field>
        </div>
        {error && (
          <p role="alert" className="text-sm text-risk-600">
            {error}
          </p>
        )}
        <Button type="submit" disabled={!file} loading={upload.isPending}>
          Upload and read it
        </Button>
      </form>
    </SectionCard>
  );
}

const LEVELS: { value: SubjectLevel; label: string }[] = [
  { value: "igcse", label: "IGCSE" },
  { value: "o_level", label: "O Level" },
  { value: "a_level", label: "A Level" },
];

interface FlatRow {
  path: number[];
  node: SyllabusTopicDraft;
}

/** A chapter's topics with their sub-topics, depth carried by `path.length`. */
function flatten(topics: SyllabusTopicDraft[], prefix: number[] = []): FlatRow[] {
  return topics.flatMap((node, i) => {
    const path = [...prefix, i];
    return [{ path, node }, ...flatten(node.children, path)];
  });
}

function updateAtPath(
  topics: SyllabusTopicDraft[],
  path: number[],
  patch: Partial<SyllabusTopicDraft>,
): SyllabusTopicDraft[] {
  const [i, ...rest] = path;
  return topics.map((node, idx) => {
    if (idx !== i) return node;
    if (rest.length === 0) return { ...node, ...patch };
    return { ...node, children: updateAtPath(node.children, rest, patch) };
  });
}

function UploadDetail({ id, onBack }: { id: number; onBack: () => void }) {
  const queryClient = useQueryClient();
  const detail = useQuery({
    queryKey: ["syllabus-upload", id],
    queryFn: () => getSyllabusUpload(id),
    refetchInterval: (query) => (query.state.data?.status === "extracting" ? 2500 : false),
  });

  const [error, setError] = useState<string | null>(null);

  const saveDraft = useMutation({
    mutationFn: (draft: SyllabusDraft) => updateSyllabusDraft(id, draft),
    // Every edit PUTs the whole draft, and each one is built from what the
    // cache holds — so the cache has to carry the previous keystroke before
    // the next one reads it. Writing it here rather than waiting for the
    // response also stops the two hazards CodeRabbit named: a second edit
    // landing before the first response drops the first edit, and a slow
    // response overwriting a newer one. The inputs stay controlled by query
    // data, never copied into useState (FE-6). A failed save resyncs.
    onMutate: (draft) => {
      // A refetch already in flight would otherwise land after this and
      // reinstate the server's older draft, so the next edit is built from it
      // and reverts this one (cubic). Deliberately not awaited: the cache write
      // below has to happen in this tick, because the next keystroke's handler
      // reads it back before React has re-rendered. Cancelling is synchronous
      // enough — an in-flight fetch can only commit on a later microtask, by
      // which time this query is already cancelled.
      void queryClient.cancelQueries({ queryKey: ["syllabus-upload", id] });
      queryClient.setQueryData(["syllabus-upload", id], (old?: SyllabusUploadDetail) =>
        old ? { ...old, draft } : old,
      );
    },
    // Take the server's metadata but keep whatever draft the cache now holds —
    // the response carries the draft as it was when this request was sent, and
    // a later keystroke may already have moved past it. Status matters:
    // editing a failed extraction flips it to `review`, and a cache still
    // reading `extraction_failed` leaves the retry button on screen, one
    // click away from re-running the AI over the tutor's edits (cubic).
    onSuccess: (saved) =>
      queryClient.setQueryData(["syllabus-upload", id], (old?: SyllabusUploadDetail) =>
        old ? { ...saved, draft: old.draft } : saved,
      ),
    onError: (err) => {
      setError(friendlyError(err, "Your last change didn't save. Try it again."));
      queryClient.invalidateQueries({ queryKey: ["syllabus-upload", id] });
    },
  });

  const retry = useMutation({
    mutationFn: () => retrySyllabusExtraction(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["syllabus-upload", id] }),
  });
  const apply = useMutation({
    mutationFn: () => applySyllabusUpload(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["syllabus-upload", id] });
      queryClient.invalidateQueries({ queryKey: ["syllabus-uploads"] });
      queryClient.invalidateQueries({ queryKey: ["subjects"] });
    },
    onError: (err) => setError(friendlyError(err, "That didn't apply. Try again.")),
  });

  const back = <BackButton onClick={onBack}>All syllabuses</BackButton>;
  if (detail.isLoading) return <PageSkeleton rows={5} label="Loading the syllabus" />;
  if (detail.isError && detail.error instanceof ApiError && detail.error.status === 404) {
    return (
      <div>
        {back}
        <NotFoundState
          title="We couldn't find that syllabus"
          body="It may have been removed. Your other syllabuses are still on the list."
        />
      </div>
    );
  }
  const upload = detail.data;
  if (detail.isError || !upload) {
    return (
      <div>
        {back}
        <ErrorState error={detail.error} onRetry={() => detail.refetch()} />
      </div>
    );
  }
  const editable = upload.status === "review" || upload.status === "extraction_failed";

  const draft = upload.draft;
  const topicCount = draft?.chapters.reduce((n, c) => n + flatten(c.topics).length, 0) ?? 0;

  /** The draft as of the last edit, not as of this render.
   *
   * `onMutate` writes each edit into the cache synchronously, but React has not
   * re-rendered by the time the next keystroke's handler runs, so the `draft`
   * in this closure can already be one edit behind. Every PUT carries the whole
   * draft, so building one from that stale copy silently reverts the previous
   * edit (CodeRabbit). Read the cache instead. */
  function latestDraft(): SyllabusDraft | null {
    return (
      queryClient.getQueryData<SyllabusUploadDetail>(["syllabus-upload", id])?.draft ??
      draft ??
      null
    );
  }

  function setChapterField(index: number, patch: Partial<SyllabusChapterDraft>) {
    const current = latestDraft();
    if (!current) return;
    saveDraft.mutate({
      ...current,
      chapters: current.chapters.map((c, i) => (i === index ? { ...c, ...patch } : c)),
    });
  }

  function setTopicField(chapter: number, path: number[], patch: Partial<SyllabusTopicDraft>) {
    const current = latestDraft();
    if (!current) return;
    setChapterField(chapter, {
      topics: updateAtPath(current.chapters[chapter].topics, path, patch),
    });
  }

  const dt = "text-xs font-medium text-ink-500";
  const dd = "mt-1 text-sm text-ink-900";
  const cell = inputClasses;

  return (
    <div>
      {back}
      <PageHeader
        eyebrow="Syllabus"
        title={upload.title}
        meta={<StatusChip status={upload.status} />}
        actions={
          // A failed extraction can leave no draft at all, and the API
          // refuses to apply nothing ("No syllabus draft to apply yet").
          editable &&
          draft && (
            <Button
              onClick={() => apply.mutate()}
              // Also while a draft save is in flight: a tutor who picks a
              // level and clicks straight through would otherwise send apply
              // before the level reaches the server, and be told to choose
              // the level they just chose (cubic).
              disabled={saveDraft.isPending}
              loading={apply.isPending}
            >
              Apply — use it with my classes
            </Button>
          )
        }
      />

      <div className="space-y-6">
        {error && (
          <p role="alert" className="rounded-lg bg-risk-100 p-3 text-sm text-risk-600">
            {error}
          </p>
        )}

        {upload.status === "extracting" && (
          <div
            role="status"
            className="flex items-start gap-3 rounded-lg bg-surface-muted p-4 text-sm text-ink-700"
          >
            <Loader2 aria-hidden className="mt-0.5 h-4 w-4 shrink-0 animate-spin text-brand-600" />
            <p>
              The AI is reading the syllabus and drafting its chapters. Long documents can take a
              minute — this page updates by itself.
            </p>
          </div>
        )}

        {upload.status === "extraction_failed" && (
          <div className="rounded-lg bg-risk-100 p-4 text-sm">
            <p className="font-medium text-risk-600">We couldn't read this syllabus.</p>
            <p className="mt-1 text-ink-700">
              Try again, or upload a clearer copy of the PDF. You can also fix the draft below by
              hand.
            </p>
            {upload.error && (
              <details className="mt-2 text-xs text-ink-500">
                <summary className="cursor-pointer">What went wrong</summary>
                <p className="mt-1">{upload.error}</p>
              </details>
            )}
            <Button
              variant="secondary"
              size="sm"
              className="mt-3"
              onClick={() => retry.mutate()}
              // Re-running extraction replaces the draft, so it must not be
              // reachable while an edit is still in flight — for that window the
              // status has not flipped to `review` yet and this button is still
              // on screen (cubic).
              disabled={saveDraft.isPending}
              loading={retry.isPending}
            >
              Try again
            </Button>
            {retry.isError && (
              <p role="alert" className="mt-2 text-risk-600">
                {friendlyError(retry.error, "That didn't start. Try again.")}
              </p>
            )}
          </div>
        )}

        {draft && (
          <SectionCard>
            <dl className="grid gap-4 sm:grid-cols-5">
              <div>
                <dt className={dt}>Exam board</dt>
                <dd className={dd}>{draft.exam_board}</dd>
              </div>
              <div>
                <dt className={dt}>Code</dt>
                <dd className={dd}>{draft.code}</dd>
              </div>
              <div>
                <dt className={dt}>Subject</dt>
                <dd className={dd}>{draft.name}</dd>
              </div>
              <div>
                <dt className={dt}>Grade scale</dt>
                <dd className={dd}>{draft.grade_scale}</dd>
              </div>
              <div>
                {editable ? (
                  <>
                    <dt>
                      <label htmlFor="syllabus-level" className={dt}>
                        Level
                      </label>
                    </dt>
                    <dd className="mt-1">
                      <Select
                        id="syllabus-level"
                        value={draft.level ?? ""}
                        onChange={(e) => {
                          const current = latestDraft();
                          if (current)
                            saveDraft.mutate({ ...current, level: e.target.value as SubjectLevel });
                        }}
                      >
                        {/* The document may not state a level, and nothing guesses one
                          for the tutor (AV-7, PROD-2) — so "not set" is a real
                          option to sit in, and applying refuses until it is set. */}
                        <option value="" disabled>
                          Choose a level
                        </option>
                        {LEVELS.map((l) => (
                          <option key={l.value} value={l.value}>
                            {l.label}
                          </option>
                        ))}
                      </Select>
                    </dd>
                  </>
                ) : (
                  <>
                    <dt className={dt}>Level</dt>
                    <dd className={dd}>
                      {LEVELS.find((l) => l.value === draft.level)?.label ?? "Not set"}
                    </dd>
                  </>
                )}
              </div>
            </dl>

            <div className="mt-6 border-t border-line pt-5">
              <SectionHeader
                title={`${plural(draft.chapters.length, "chapter", "chapters")}, ${plural(topicCount, "topic", "topics")}`}
                description={
                  editable
                    ? "Correct any code or title the AI got wrong. Each change saves as you type."
                    : undefined
                }
              />

              <div className="mt-4 space-y-4">
                {/* Keyed by index deliberately, against the usual rule: a chapter's
                    code is what the tutor is editing, so keying on it would change
                    the key on every keystroke and pull focus out of the input. The
                    list is never reordered or filtered here. */}
                {draft.chapters.map((chapter, chapterIndex) => (
                  <div key={chapterIndex} className="overflow-hidden rounded-lg border border-line">
                    <div className="flex items-center gap-2 border-b border-line bg-surface-muted px-3 py-2">
                      {editable ? (
                        <>
                          <label className="sr-only" htmlFor={`chapter-code-${chapterIndex}`}>
                            Chapter code
                          </label>
                          <div className="w-20 shrink-0">
                            <input
                              id={`chapter-code-${chapterIndex}`}
                              className={cell}
                              value={chapter.code}
                              onChange={(e) =>
                                setChapterField(chapterIndex, { code: e.target.value })
                              }
                            />
                          </div>
                          <label className="sr-only" htmlFor={`chapter-title-${chapterIndex}`}>
                            Chapter title
                          </label>
                          <input
                            id={`chapter-title-${chapterIndex}`}
                            className={`${cell} font-medium`}
                            value={chapter.title}
                            onChange={(e) =>
                              setChapterField(chapterIndex, { title: e.target.value })
                            }
                          />
                        </>
                      ) : (
                        <p className="text-sm font-medium text-ink-900">
                          {chapter.title}
                          <span className="ml-2 font-normal text-ink-500">{chapter.code}</span>
                        </p>
                      )}
                    </div>

                    {chapter.topics.length === 0 ? (
                      <p className="px-3 py-3 text-sm text-ink-500">No topics in this chapter.</p>
                    ) : (
                      <table className="w-full text-sm">
                        <thead>
                          <tr className="border-b border-line text-left text-xs text-ink-500">
                            <th className="py-2 pl-3 pr-2 font-medium">Code</th>
                            <th className="py-2 pr-2 font-medium">Topic</th>
                            <th className="py-2 pr-3 font-medium">Weight</th>
                          </tr>
                        </thead>
                        <tbody>
                          {flatten(chapter.topics).map(({ path, node }) => (
                            <tr
                              key={path.join(".")}
                              className="border-b border-line align-middle last:border-0"
                            >
                              <td
                                className="py-1.5 pr-2 pl-3 text-ink-500"
                                style={{ paddingLeft: `${12 + (path.length - 1) * 16}px` }}
                              >
                                {editable ? (
                                  <div className="w-20">
                                    <input
                                      aria-label="Topic code"
                                      className={cell}
                                      value={node.code}
                                      onChange={(e) =>
                                        setTopicField(chapterIndex, path, { code: e.target.value })
                                      }
                                    />
                                  </div>
                                ) : (
                                  node.code
                                )}
                              </td>
                              <td className="py-1.5 pr-2 text-ink-900">
                                {editable ? (
                                  <input
                                    aria-label="Topic title"
                                    className={cell}
                                    value={node.title}
                                    onChange={(e) =>
                                      setTopicField(chapterIndex, path, { title: e.target.value })
                                    }
                                  />
                                ) : (
                                  node.title
                                )}
                              </td>
                              <td className="py-1.5 pr-3 tabular-nums text-ink-700">
                                {editable ? (
                                  <div className="w-20">
                                    <input
                                      type="number"
                                      aria-label="Topic weight"
                                      step={0.1}
                                      min={0.1}
                                      className={cell}
                                      value={node.weight}
                                      onChange={(e) =>
                                        setTopicField(chapterIndex, path, {
                                          weight: Number(e.target.value),
                                        })
                                      }
                                    />
                                  </div>
                                ) : (
                                  node.weight
                                )}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    )}
                  </div>
                ))}
              </div>
            </div>
          </SectionCard>
        )}
      </div>
    </div>
  );
}

export default function SyllabusUploadPage() {
  const uploads = useQuery({ queryKey: ["syllabus-uploads"], queryFn: listSyllabusUploads });
  const [selectedId, setSelectedId] = useState<number | null>(null);

  if (selectedId !== null) {
    return <UploadDetail id={selectedId} onBack={() => setSelectedId(null)} />;
  }

  return (
    <div>
      <PageHeader
        title="Syllabuses"
        description="Upload an exam board's syllabus and the AI drafts its chapters and topics. You check them before they shape teaching plans, readiness and homework."
        back={{ to: "/tutor/library", label: "Library" }}
      />

      <div className="space-y-6">
        <UploadForm onUploaded={setSelectedId} />

        <SectionCard>
          <SectionHeader title="Your syllabuses" />
          <div className="mt-3">
            {uploads.isLoading ? (
              <SectionSkeleton rows={3} label="Loading your syllabuses" />
            ) : uploads.isError ? (
              <ErrorState error={uploads.error} onRetry={() => uploads.refetch()} />
            ) : uploads.data?.length === 0 ? (
              <EmptyState
                title="No syllabuses uploaded yet."
                hint="Upload one above to build its chapters and topics."
              />
            ) : (
              <ul className="-mx-2 divide-y divide-line">
                {uploads.data?.map((u) => (
                  <li key={u.id}>
                    <button
                      type="button"
                      onClick={() => setSelectedId(u.id)}
                      className="group flex w-full items-center gap-3 rounded-md px-2 py-3 text-left text-sm transition-colors hover:bg-surface-muted"
                    >
                      <span className="min-w-0 flex-1 truncate font-medium text-ink-900 group-hover:text-brand-600">
                        {u.title}
                      </span>
                      <StatusChip status={u.status} />
                      <ChevronRight aria-hidden className="h-4 w-4 shrink-0 text-ink-500" />
                    </button>
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
