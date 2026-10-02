import { useState, type FormEvent } from "react";
import { useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Clock } from "lucide-react";
import {
  MAX_TYPED_ANSWER,
  myAssignments,
  mySubmission,
  requestRemark,
  submitWork,
  type StudentMarkRow,
} from "../api/homework";
import { ApiError } from "../api/client";
import { Button, Field, FileInput, Textarea } from "../components/controls";
import { ErrorState, NotFoundState, PageHeader, PageSkeleton } from "../components/page";
import { SectionCard } from "../components/ui";
import { friendlyError } from "../lib/errors";

const BACK = { to: "/student/homework", label: "Homework" };

export default function SubmitHomeworkPage() {
  const { assignmentId } = useParams();
  const id = Number(assignmentId);
  const queryClient = useQueryClient();

  const view = useQuery({
    queryKey: ["my-submission", id],
    queryFn: () => mySubmission(id),
    refetchInterval: (query) => (query.state.data?.status === "being_marked" ? 4000 : false),
  });
  // The submission view carries no title, so "Your marked homework" could not
  // say *which* homework. The student's assignment list — the same cached query
  // the Homework and Home pages read — does, so the title comes from there.
  const assignments = useQuery({ queryKey: ["my-assignments"], queryFn: myAssignments });
  const assignment = assignments.data?.find((a) => a.id === id);
  const title = assignment?.title ?? "Homework";

  const [files, setFiles] = useState<File[]>([]);
  // Bumped after a successful upload so the file picker forgets the names it
  // was showing — the files have gone, and still listing them would read as
  // "not sent yet".
  const [pickerKey, setPickerKey] = useState(0);
  const [typed, setTyped] = useState("");
  const [error, setError] = useState<string | null>(null);

  const submit = useMutation({
    mutationFn: () => submitWork(id, files, typed),
    onSuccess: () => {
      setFiles([]);
      setPickerKey((k) => k + 1);
      setTyped("");
      queryClient.invalidateQueries({ queryKey: ["my-submission", id] });
      queryClient.invalidateQueries({ queryKey: ["my-assignments"] });
    },
    onError: (err) => setError(friendlyError(err, "Your work couldn't be sent. Try again.")),
  });

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    // Either channel, or both (AV-73) — the server enforces the same rule.
    if (files.length || typed.trim()) submit.mutate();
  }

  if (view.isLoading) return <PageSkeleton rows={3} label="Loading your homework" />;
  if (view.isError && view.error instanceof ApiError && view.error.status === 404) {
    return (
      <NotFoundState
        title="We couldn't find that homework"
        body="It may have been removed by your tutor, or the link may be wrong."
        back={{ to: BACK.to, label: "Back to homework" }}
      />
    );
  }
  if (view.isError || !view.data) {
    return (
      <div className="max-w-2xl">
        <PageHeader title={title} back={BACK} />
        <ErrorState
          title="Couldn't load this homework."
          error={view.error}
          onRetry={() => void view.refetch()}
        />
      </div>
    );
  }
  const v = view.data;
  const subject = assignment?.subject_name;

  if (v.status === "marked") {
    return (
      <div className="max-w-2xl space-y-6">
        <PageHeader
          title={title}
          back={BACK}
          eyebrow={subject ? `${subject} · Marked` : "Marked"}
          description="Your marks and your tutor's feedback, question by question."
        />

        <SectionCard className="flex items-center gap-4">
          <CheckCircle2 aria-hidden className="h-6 w-6 shrink-0 text-ok-700" />
          {/* An absent total is words, never a dash or a zero (PROD-2). */}
          {v.total === null ? (
            <p className="text-ink-700">Your total isn&apos;t ready yet.</p>
          ) : (
            <p className="text-ink-700">
              You scored{" "}
              <span className="font-display text-2xl tabular-nums text-ink-900">{v.total}</span> out
              of <span className="tabular-nums">{v.total_max}</span> marks
            </p>
          )}
        </SectionCard>

        <section className="space-y-3">
          <h2 className="avora-label">Question by question</h2>
          {v.marks.map((m) => (
            <MarkedQuestion
              key={m.number}
              submissionId={v.submission_id}
              mark={m}
              assignmentId={id}
            />
          ))}
        </section>
      </div>
    );
  }

  return (
    <div className="max-w-2xl space-y-6">
      <PageHeader
        title={title}
        back={BACK}
        eyebrow={subject}
        description={
          v.status === "being_marked"
            ? undefined
            : "Upload clear photos or a scan of your handwritten answers, every page in order — or type your answers. You can do both."
        }
      />

      {v.status === "being_marked" ? (
        <div
          aria-live="polite"
          className="flex gap-3 rounded-xl border border-line bg-warn-100 p-4 text-sm text-warn-700"
        >
          <Clock aria-hidden className="mt-0.5 h-4 w-4 shrink-0" />
          <p>
            Your work is in and your tutor is marking it. Your marks and feedback will appear here
            when they&apos;re ready — this page checks for them automatically.
          </p>
        </div>
      ) : (
        <>
          {v.status === "submitted" && (
            <div className="flex gap-3 rounded-xl border border-line bg-ok-100 p-4 text-sm text-ok-700">
              <CheckCircle2 aria-hidden className="mt-0.5 h-4 w-4 shrink-0" />
              <p>Submitted. You can upload again before it&apos;s marked if you need to.</p>
            </div>
          )}
          <SectionCard>
            <form onSubmit={onSubmit} className="space-y-5">
              <Field label="Photos or a scan of your answers">
                <FileInput
                  key={pickerKey}
                  multiple
                  accept="application/pdf,image/*,.heic,.heif"
                  onFiles={setFiles}
                  prompt="Choose photos or a PDF"
                  hint="JPG, PNG, HEIC or PDF — add every page, in order"
                />
              </Field>
              <Field
                label="Or type your answers"
                hint="You'll see your marks once your tutor has finished — nothing is shown while you're still working."
              >
                {/* AV-92: marks and feedback appear only after the tutor signs
                    off, and there is deliberately no in-progress feedback here.
                    Saying so is better than a student wondering whether typing
                    more will show them something. */}
                <Textarea
                  rows={10}
                  maxLength={MAX_TYPED_ANSWER}
                  value={typed}
                  onChange={(e) => setTyped(e.target.value)}
                  placeholder={"1. ...\n2. ..."}
                />
              </Field>
              {error && (
                <p role="alert" className="text-sm text-risk-600">
                  {error}
                </p>
              )}
              {/* Channel-neutral: typed-only work uploads nothing (cubic). */}
              <Button
                type="submit"
                loading={submit.isPending}
                disabled={files.length === 0 && typed.trim() === ""}
              >
                Submit work
              </Button>
            </form>
          </SectionCard>
        </>
      )}
    </div>
  );
}

function MarkedQuestion({
  submissionId,
  assignmentId,
  mark,
}: {
  submissionId: number | null;
  assignmentId: number;
  mark: StudentMarkRow;
}) {
  const queryClient = useQueryClient();
  const [asking, setAsking] = useState(false);
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);

  const ask = useMutation({
    mutationFn: () => requestRemark(submissionId!, mark.question_id!, reason),
    onSuccess: () => {
      setAsking(false);
      queryClient.invalidateQueries({ queryKey: ["my-submission", assignmentId] });
    },
    onError: (err) => setError(friendlyError(err, "Your request couldn't be sent. Try again.")),
  });

  const canAsk = submissionId !== null && mark.question_id !== null && mark.remark_status === null;

  return (
    <SectionCard>
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="font-medium text-ink-900">Question {mark.number}</p>
          {mark.text_summary && <p className="mt-0.5 text-sm text-ink-500">{mark.text_summary}</p>}
        </div>
        {/* A question with no mark says so; it is never shown as 0 (PROD-2). */}
        <span className="shrink-0 rounded-md bg-surface-muted px-2 py-1 text-sm font-medium tabular-nums text-ink-900">
          {mark.final_marks === null
            ? "Not marked"
            : `${mark.final_marks} / ${mark.max_marks} ${mark.max_marks === 1 ? "mark" : "marks"}`}
        </span>
      </div>

      {mark.final_feedback && (
        <p className="mt-3 border-l-2 border-line pl-3 text-sm leading-relaxed text-ink-700">
          {mark.final_feedback}
        </p>
      )}

      {mark.remark_status === "open" && (
        <p className="mt-3 text-sm text-remark-600">
          Your tutor has been asked to look at this one again.
        </p>
      )}
      {mark.remark_status === "resolved" && (
        <p className="mt-3 text-sm text-ink-500">
          Your tutor has already re-checked this question.
        </p>
      )}

      {canAsk &&
        (asking ? (
          <div className="mt-4 space-y-3 border-t border-line pt-4">
            <Field
              label="Why do you think this mark should change?"
              optional
              hint="Your tutor decides — you can only ask once per question."
            >
              <Textarea rows={2} value={reason} onChange={(e) => setReason(e.target.value)} />
            </Field>
            {error && (
              <p role="alert" className="text-sm text-risk-600">
                {error}
              </p>
            )}
            <div className="flex gap-2">
              <Button size="sm" loading={ask.isPending} onClick={() => ask.mutate()}>
                Send to my tutor
              </Button>
              <Button variant="ghost" size="sm" onClick={() => setAsking(false)}>
                Cancel
              </Button>
            </div>
          </div>
        ) : (
          <div className="mt-3">
            <Button variant="secondary" size="sm" onClick={() => setAsking(true)}>
              Request a remark
            </Button>
          </div>
        ))}
    </SectionCard>
  );
}
