import { useMemo, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { listGroups, listSubjects } from "../api/groups";
import { listMocks, retryMock, uploadMock, type Mock } from "../api/mocks";
import { Button, Field, FileInput, Input, Select } from "../components/controls";
import { ErrorState, SectionSkeleton } from "../components/page";
import { SubjectSection } from "../components/SubjectGroups";
import { EmptyState, SectionCard, SectionHeader } from "../components/ui";
import { friendlyError } from "../lib/errors";
import { formatDuration } from "../lib/schedule";
import { groupBySubject } from "../lib/subjectGroups";

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

/** The one status line a mock gets. Ordered like the past-papers line: a failed
 *  read keeps a question count of zero, so the failure is tested first and the
 *  tutor is never told it is still being read once it has given up. The raw
 *  reason sits behind "What went wrong", not in the line itself. */
export function mockStatusLine(m: Mock): string {
  if (m.status === "extraction_failed")
    return "Couldn't read this paper. Try again, or upload a clearer copy as a new mock.";
  if (m.status === "extracting") return "Reading the paper…";
  if (m.status === "closed") return "Closed";
  if (m.question_count === 0) return "No questions read";
  const marks = m.total_marks ? ` · ${m.total_marks} marks` : "";
  return `${plural(m.question_count, "question", "questions")}${marks}`;
}

export default function MarkedMocks() {
  const queryClient = useQueryClient();
  const mocks = useQuery({
    queryKey: ["mocks"],
    queryFn: listMocks,
    // The AI reads the paper in a background job. Self-terminating: the
    // interval returns false once nothing is mid-read.
    refetchInterval: (query) =>
      query.state.data?.some((m) => m.status === "extracting") ? 3000 : false,
  });
  const subjects = useQuery({ queryKey: ["subjects"], queryFn: listSubjects });
  const groups = useQuery({ queryKey: ["groups"], queryFn: listGroups });

  const [subjectId, setSubjectId] = useState("");
  const [title, setTitle] = useState("");
  const [duration, setDuration] = useState("");
  const [satOn, setSatOn] = useState("");
  const [paper, setPaper] = useState<File | null>(null);
  const [markScheme, setMarkScheme] = useState<File | null>(null);
  // Bumped after an upload so both pickers remount: clearing the files alone
  // would leave them still naming what was just sent.
  const [pickerKey, setPickerKey] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [added, setAdded] = useState(false);
  // Any edit starts a fresh attempt: the old error and "Added" no longer apply.
  const edit = (set: (v: string) => void) => (e: { target: { value: string } }) => {
    setError(null);
    setAdded(false);
    set(e.target.value);
  };

  const upload = useMutation({
    mutationFn: () =>
      uploadMock({
        subject_id: Number(subjectId),
        title: title.trim(),
        paper: paper!,
        mark_scheme: markScheme,
        duration_minutes: duration ? Number(duration) : null,
        sat_on: satOn || null,
      }),
    onSuccess: () => {
      setTitle("");
      setDuration("");
      setSatOn("");
      setPaper(null);
      setMarkScheme(null);
      setPickerKey((k) => k + 1);
      setAdded(true);
      queryClient.invalidateQueries({ queryKey: ["mocks"] });
    },
    onError: (err) => setError(friendlyError(err, "That mock didn't upload. Try again.")),
  });

  const retry = useMutation({
    mutationFn: retryMock,
    onSuccess: (updated) => {
      queryClient.setQueryData<Mock[]>(["mocks"], (rows) =>
        rows?.map((row) => (row.id === updated.id ? updated : row)),
      );
      queryClient.invalidateQueries({ queryKey: ["mocks"] });
    },
    // A refusal usually means the row is out of date.
    onError: () => queryClient.invalidateQueries({ queryKey: ["mocks"] }),
  });

  const grouped = useMemo(
    () => groupBySubject(mocks.data, subjects.isSuccess ? subjects.data : undefined),
    [mocks.data, subjects.data, subjects.isSuccess],
  );
  const className = (id: number | null) => groups.data?.find((g) => g.id === id)?.name;

  const ready = subjectId && title.trim() && paper;

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setAdded(false);
    if (ready) upload.mutate();
  }

  const list = (items: Mock[]) => (
    <ul className="divide-y divide-line text-sm">
      {items.map((m) => (
        <li key={m.id} className="py-3">
          <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
            <div className="min-w-0">
              <Link
                to={`/tutor/mocks/${m.id}`}
                className="font-medium text-brand-600 hover:text-brand-700"
              >
                {m.title}
              </Link>
              <p
                className={m.status === "extraction_failed" ? "text-risk-600" : "text-ink-500"}
                aria-live="polite"
              >
                {mockStatusLine(m)}
                {m.duration_minutes && m.status === "published"
                  ? ` · ${formatDuration(m.duration_minutes)} allowed`
                  : ""}
              </p>
              {m.status === "published" && (
                <p className="text-ink-500">
                  {m.group_id
                    ? `Open to ${className(m.group_id) ?? "a class"}`
                    : "Not open to a class yet"}
                </p>
              )}
              {m.status === "extraction_failed" && m.extraction_error && (
                <details className="mt-1 text-xs text-ink-500">
                  <summary className="cursor-pointer">What went wrong</summary>
                  <p className="mt-1">{m.extraction_error}</p>
                </details>
              )}
              {retry.isError && retry.variables === m.id && (
                <p role="alert" className="mt-1 text-risk-600">
                  {friendlyError(retry.error, "That didn't start. Try again.")}
                </p>
              )}
            </div>
            {m.status === "extraction_failed" && (
              <Button
                variant="secondary"
                size="sm"
                loading={retry.isPending && retry.variables === m.id}
                onClick={() => retry.mutate(m.id)}
              >
                Try again
                <span className="sr-only"> to read {m.title}</span>
              </Button>
            )}
          </div>
        </li>
      ))}
    </ul>
  );

  return (
    <div className="space-y-6">
      <SectionHeader
        title="Marked by the AI"
        description="Upload a mock paper and the AI reads its questions, then marks what your students hand in. Nothing reaches students until you open it to a class."
        level="h2"
      />
      <SectionCard>
        <form onSubmit={onSubmit} className="space-y-4">
          <SectionHeader level="h3" title="Add a mock" />
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Subject">
              <Select value={subjectId} onChange={edit(setSubjectId)}>
                <option value="">Choose a subject</option>
                {subjects.data?.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name} ({s.exam_board})
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Title">
              <Input
                value={title}
                maxLength={200}
                onChange={edit(setTitle)}
                placeholder="e.g. Year 11 Chemistry mock"
              />
            </Field>
            <Field
              label="Time allowed, in minutes"
              optional
              hint="Leave it empty and the mock is untimed."
            >
              <Input
                type="number"
                min={1}
                inputMode="numeric"
                value={duration}
                onChange={edit(setDuration)}
                placeholder="e.g. 90"
              />
            </Field>
            <Field label="Date it is sat" optional>
              <Input type="date" value={satOn} onChange={edit(setSatOn)} />
            </Field>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Question paper">
              <FileInput
                key={`paper-${pickerKey}`}
                accept="application/pdf,image/*"
                prompt="Choose the question paper"
                hint="PDF or photo"
                onFiles={(files) => {
                  setError(null);
                  setAdded(false);
                  setPaper(files[0] ?? null);
                }}
              />
            </Field>
            <Field label="Mark scheme" optional>
              <FileInput
                key={`scheme-${pickerKey}`}
                accept="application/pdf,image/*"
                prompt="Choose the mark scheme"
                hint="PDF or photo"
                onFiles={(files) => {
                  setError(null);
                  setAdded(false);
                  setMarkScheme(files[0] ?? null);
                }}
              />
            </Field>
          </div>
          <p className="text-sm text-ink-500">
            {markScheme
              ? "Marks that match the scheme and read clearly are finalized for you; the rest come to you to check."
              : "Without a mark scheme, no mark is finalized for you — every one waits for you to check it before it counts."}
          </p>
          {error && (
            <p role="alert" className="text-sm text-risk-600">
              {error}
            </p>
          )}
          {added && (
            <p role="status" className="text-sm text-ink-700">
              Added. The AI is reading it.
            </p>
          )}
          <Button type="submit" disabled={!ready} loading={upload.isPending}>
            Add mock
          </Button>
        </form>
      </SectionCard>

      <SectionCard>
        <SectionHeader title="Your mocks" level="h3" />
        <div className="mt-3">
          {mocks.isLoading ? (
            <SectionSkeleton rows={3} label="Loading your mocks" />
          ) : mocks.isError ? (
            <ErrorState error={mocks.error} onRetry={() => mocks.refetch()} />
          ) : mocks.data?.length === 0 ? (
            <EmptyState
              title="No mocks uploaded yet."
              hint="Add one above and the AI starts reading its questions."
            />
          ) : subjects.isSuccess ? (
            <div className="space-y-5">
              {grouped.map((g) => (
                <SubjectSection key={g.id} subject={g.subject}>
                  {list(g.items)}
                </SubjectSection>
              ))}
            </div>
          ) : (
            list(mocks.data ?? [])
          )}
        </div>
      </SectionCard>
    </div>
  );
}
