import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Loader2, Plus, X } from "lucide-react";
import {
  getAssignment,
  listSubmissions,
  publishAssignment,
  replaceQuestions,
  retryExtraction,
  type QuestionIn,
} from "../api/homework";
import { listTopics } from "../api/syllabus";
import { getGroup } from "../api/groups";
import { ApiError } from "../api/client";
import { friendlyError } from "../lib/errors";
import { assignmentStatus } from "../lib/assignmentStatus";
import { EmptyState, SectionCard } from "../components/ui";
import { Button, buttonClasses, inputClasses } from "../components/controls";
import {
  ErrorState,
  NotFoundState,
  PageHeader,
  PageSkeleton,
  SectionSkeleton,
} from "../components/page";

interface EditableQuestion extends QuestionIn {
  key: number;
}

/** A submission's state, in words — never the raw enum. */
const SUBMISSION_STATUS: Record<string, { label: string; classes: string }> = {
  submitted: { label: "Waiting to be marked", classes: "bg-surface-muted text-ink-700" },
  marking: { label: "Being marked…", classes: "bg-surface-muted text-ink-700" },
  ai_marked: { label: "AI draft ready", classes: "bg-warn-100 text-warn-700" },
  ai_failed: { label: "AI couldn't mark — mark it yourself", classes: "bg-risk-100 text-risk-600" },
  needs_review: { label: "Needs your review", classes: "bg-warn-100 text-warn-700" },
  auto_finalized: { label: "Marked automatically", classes: "bg-ok-100 text-ok-700" },
  finalized: { label: "Finalized", classes: "bg-ok-100 text-ok-700" },
};

/** Statuses where the tutor has something to decide. */
const NEEDS_TUTOR = new Set(["ai_marked", "ai_failed", "needs_review"]);

/** The shared control look at the denser size a table row needs. Width is left
    to each cell, so it is stripped here rather than fought with an override. */
const CELL_INPUT = inputClasses.replace("h-10", "h-9").replace("w-full", "");
const MULTI_SELECT = `${inputClasses.replace("h-10", "")} py-1`;

export default function AssignmentDetailPage() {
  const { assignmentId } = useParams();
  const id = Number(assignmentId);
  const queryClient = useQueryClient();

  const assignment = useQuery({
    queryKey: ["assignment", id],
    queryFn: () => getAssignment(id),
    refetchInterval: (query) => (query.state.data?.status === "extracting" ? 2500 : false),
  });
  const group = useQuery({
    queryKey: ["group", assignment.data?.group_id],
    queryFn: () => getGroup(assignment.data!.group_id),
    enabled: !!assignment.data,
  });
  const topics = useQuery({
    queryKey: ["topics", group.data?.subject.id],
    queryFn: () => listTopics(group.data!.subject.id),
    enabled: !!group.data,
  });
  const submissions = useQuery({
    queryKey: ["submissions", id],
    queryFn: () => listSubmissions(id),
    enabled: assignment.data?.status === "published" || assignment.data?.status === "closed",
    refetchInterval: 5000,
  });

  const [rows, setRows] = useState<EditableQuestion[]>([]);
  const [dirty, setDirty] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (assignment.data && !dirty) {
      setRows(
        assignment.data.questions.map((q, i) => ({
          key: i,
          number: q.number,
          text_summary: q.text_summary,
          max_marks: q.max_marks,
          has_mark_scheme: q.has_mark_scheme,
          topic_ids: q.topics.map((t) => t.id),
        })),
      );
    }
  }, [assignment.data, dirty]);

  const save = useMutation({
    mutationFn: () =>
      replaceQuestions(
        id,
        rows.map(({ key, ...q }) => q),
      ),
    onSuccess: () => {
      setDirty(false);
      queryClient.invalidateQueries({ queryKey: ["assignment", id] });
    },
    onError: (err) => setError(friendlyError(err)),
  });
  const publish = useMutation({
    mutationFn: async () => {
      if (dirty)
        await replaceQuestions(
          id,
          rows.map(({ key, ...q }) => q),
        );
      return publishAssignment(id);
    },
    onSuccess: () => {
      setDirty(false);
      queryClient.invalidateQueries({ queryKey: ["assignment", id] });
    },
    onError: (err) => setError(friendlyError(err)),
  });
  const retry = useMutation({
    mutationFn: () => retryExtraction(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["assignment", id] }),
  });

  const topicById = useMemo(
    () => new Map((topics.data ?? []).map((t) => [t.id, t])),
    [topics.data],
  );

  if (assignment.isLoading) return <PageSkeleton label="Loading homework" />;
  if (
    assignment.isError &&
    assignment.error instanceof ApiError &&
    assignment.error.status === 404
  ) {
    return (
      <NotFoundState
        title="We couldn't find that homework"
        body="It may have been deleted, or the link may be wrong."
        back={{ to: "/tutor/classes", label: "All classes" }}
      />
    );
  }
  if (assignment.isError || !assignment.data) {
    return (
      <ErrorState
        title="This homework didn't load"
        error={assignment.error}
        onRetry={() => assignment.refetch()}
      />
    );
  }
  const a = assignment.data;
  const editable = a.status === "review" || a.status === "extraction_failed";
  // The one screen that names the step after checking: the Publish button is
  // right here in the header, where the class's homework list has none.
  const status = assignmentStatus(a.status, { review: "Check the questions, then publish" });
  const totalMarks = rows.reduce((sum, r) => sum + (r.max_marks || 0), 0);

  function update(key: number, patch: Partial<EditableQuestion>) {
    setRows((prev) => prev.map((r) => (r.key === key ? { ...r, ...patch } : r)));
    setDirty(true);
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title={a.title}
        back={{
          to: `/tutor/groups/${a.group_id}/homework`,
          label: group.data?.name ?? "Back to class",
        }}
        meta={
          <>
            <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${status.classes}`}>
              {status.label}
            </span>
            {a.question_range && (
              <span className="text-ink-500">Questions: {a.question_range}</span>
            )}
          </>
        }
        actions={
          editable && (
            <>
              <Button
                variant="secondary"
                onClick={() => save.mutate()}
                disabled={!dirty}
                loading={save.isPending}
              >
                Save changes
              </Button>
              <Button
                onClick={() => publish.mutate()}
                disabled={rows.length === 0}
                loading={publish.isPending}
              >
                Publish to students
              </Button>
            </>
          )
        }
      />

      {error && (
        <p role="alert" className="rounded-md bg-risk-100 px-3 py-2 text-sm text-risk-600">
          {error}
        </p>
      )}

      {a.status === "extracting" && (
        <SectionCard className="flex items-start gap-3">
          <Loader2 aria-hidden className="mt-0.5 h-5 w-5 shrink-0 animate-spin text-brand-600" />
          <p className="text-sm text-ink-700" aria-live="polite">
            Reading the paper and building the question list. This usually takes under a minute —
            the page updates by itself.
          </p>
        </SectionCard>
      )}

      {a.status === "extraction_failed" && (
        <div className="rounded-xl border border-line bg-risk-100 p-4 text-sm text-ink-900">
          <p className="font-medium">We couldn't read the questions from this paper.</p>
          <p className="mt-1 text-ink-700">
            Try reading it again, or add the questions yourself below and publish.
          </p>
          <Button
            variant="secondary"
            size="sm"
            className="mt-3"
            loading={retry.isPending}
            onClick={() => retry.mutate()}
          >
            Try reading it again
          </Button>
          {/* The job's own reason is kept for whoever has to fix it, but folded
              away: a raw exception string is not a message for a tutor. */}
          {a.extraction_error && (
            <details className="mt-3 text-xs text-ink-500">
              <summary className="cursor-pointer">Technical details</summary>
              <p className="mt-1 break-words font-mono">{a.extraction_error}</p>
            </details>
          )}
        </div>
      )}

      {(editable || a.questions.length > 0) && a.status !== "extracting" && (
        <SectionCard>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-lg text-ink-900">Questions</h2>
              <p className="text-sm text-ink-500">
                {rows.length} {rows.length === 1 ? "question" : "questions"} · {totalMarks}{" "}
                {totalMarks === 1 ? "mark" : "marks"} in total
              </p>
            </div>
            {editable && (
              <Button
                variant="secondary"
                size="sm"
                onClick={() => {
                  setRows((prev) => [
                    ...prev,
                    {
                      key: Date.now(),
                      number: String(prev.length + 1),
                      text_summary: "",
                      max_marks: 1,
                      has_mark_scheme: false,
                      topic_ids: [],
                    },
                  ]);
                  setDirty(true);
                }}
              >
                <Plus aria-hidden className="h-4 w-4" />
                Add question
              </Button>
            )}
          </div>

          {rows.length === 0 ? (
            <EmptyState
              title="No questions yet"
              hint="Add the questions students will answer, then publish."
            />
          ) : (
            <div className="-mx-5 mt-4 overflow-x-auto px-5">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-line text-left text-xs text-ink-500">
                    <th scope="col" className="py-2 pr-3 font-medium">
                      Question
                    </th>
                    <th scope="col" className="py-2 pr-3 font-medium">
                      What it asks
                    </th>
                    <th scope="col" className="py-2 pr-3 font-medium">
                      Marks
                    </th>
                    <th scope="col" className="py-2 pr-3 font-medium">
                      Mark scheme
                    </th>
                    <th scope="col" className="py-2 font-medium">
                      Topics
                    </th>
                    {editable && (
                      <th scope="col" className="py-2 pl-2">
                        <span className="sr-only">Remove</span>
                      </th>
                    )}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r, index) => (
                    <tr key={r.key} className="border-b border-line align-top last:border-0">
                      <td className="py-2 pr-3">
                        {editable ? (
                          <input
                            aria-label={`Question number, row ${index + 1}`}
                            className={`${CELL_INPUT} w-16`}
                            value={r.number}
                            onChange={(e) => update(r.key, { number: e.target.value })}
                          />
                        ) : (
                          <span className="font-medium text-ink-900">Q{r.number}</span>
                        )}
                      </td>
                      <td className="py-2 pr-3 text-ink-700">
                        {editable ? (
                          <input
                            aria-label={`Question ${r.number}: what it asks`}
                            className={`${CELL_INPUT} w-full min-w-[12rem]`}
                            value={r.text_summary}
                            onChange={(e) => update(r.key, { text_summary: e.target.value })}
                          />
                        ) : (
                          r.text_summary
                        )}
                      </td>
                      <td className="py-2 pr-3 tabular-nums text-ink-700">
                        {editable ? (
                          <input
                            type="number"
                            min={1}
                            aria-label={`Question ${r.number}: marks`}
                            className={`${CELL_INPUT} w-20`}
                            value={r.max_marks}
                            onChange={(e) => update(r.key, { max_marks: Number(e.target.value) })}
                          />
                        ) : (
                          r.max_marks
                        )}
                      </td>
                      <td className="py-2 pr-3">
                        {editable ? (
                          <label className="flex h-9 items-center gap-2 text-ink-700">
                            <input
                              type="checkbox"
                              className="h-4 w-4 accent-brand-600"
                              checked={r.has_mark_scheme}
                              onChange={(e) => update(r.key, { has_mark_scheme: e.target.checked })}
                            />
                            <span>
                              Official
                              <span className="sr-only"> mark scheme for question {r.number}</span>
                            </span>
                          </label>
                        ) : r.has_mark_scheme ? (
                          <span className="inline-flex items-center gap-1 text-ok-700">
                            <Check aria-hidden className="h-4 w-4" />
                            Official
                          </span>
                        ) : (
                          <span className="text-warn-700">None — you mark this one</span>
                        )}
                      </td>
                      <td className="py-2">
                        {editable ? (
                          <select
                            multiple
                            size={3}
                            aria-label={`Question ${r.number}: topics`}
                            className={`${MULTI_SELECT} min-w-[12rem]`}
                            value={r.topic_ids.map(String)}
                            onChange={(e) =>
                              update(r.key, {
                                topic_ids: Array.from(e.target.selectedOptions, (o) =>
                                  Number(o.value),
                                ),
                              })
                            }
                          >
                            {topics.data?.map((t) => (
                              <option key={t.id} value={t.id}>
                                {t.title} ({t.code})
                              </option>
                            ))}
                          </select>
                        ) : r.topic_ids.length > 0 ? (
                          <span className="flex flex-wrap gap-1">
                            {r.topic_ids.map((topicId) => {
                              const t = topicById.get(topicId);
                              return (
                                <span
                                  key={topicId}
                                  title={t?.code}
                                  className="rounded bg-surface-muted px-1.5 py-0.5 text-xs text-ink-700"
                                >
                                  {t ? t.title : topics.isLoading ? "Loading…" : "Unknown topic"}
                                </span>
                              );
                            })}
                          </span>
                        ) : (
                          <span className="text-ink-500">No topic linked</span>
                        )}
                      </td>
                      {editable && (
                        <td className="py-2 pl-2">
                          <Button
                            variant="ghost"
                            size="sm"
                            aria-label={`Remove question ${r.number}`}
                            onClick={() => {
                              setRows((prev) => prev.filter((x) => x.key !== r.key));
                              setDirty(true);
                            }}
                          >
                            <X aria-hidden className="h-4 w-4" />
                          </Button>
                        </td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {editable && (
            <p className="mt-3 text-xs text-ink-500">
              The AI only marks questions with an official mark scheme. The rest wait for you.
            </p>
          )}
        </SectionCard>
      )}

      {(a.status === "published" || a.status === "closed") && (
        <SectionCard>
          <h2 className="text-lg text-ink-900">Submissions</h2>
          {submissions.isLoading ? (
            <div className="mt-3">
              <SectionSkeleton rows={3} label="Loading submissions" />
            </div>
          ) : submissions.isError ? (
            <div
              role="alert"
              className="mt-3 flex flex-wrap items-center justify-between gap-2 text-sm text-ink-500"
            >
              <span>Submissions didn't load. This is usually temporary.</span>
              <Button variant="secondary" size="sm" onClick={() => submissions.refetch()}>
                Try again
              </Button>
            </div>
          ) : submissions.data && submissions.data.length > 0 ? (
            <ul className="mt-3 divide-y divide-line">
              {submissions.data.map((s) => {
                const settled = s.status === "finalized" || s.status === "auto_finalized";
                const needsTutor = NEEDS_TUTOR.has(s.status);
                const badge = SUBMISSION_STATUS[s.status] ?? {
                  label: "In progress",
                  classes: "bg-surface-muted text-ink-700",
                };
                return (
                  <li
                    key={s.id}
                    className="flex flex-wrap items-center justify-between gap-3 py-2.5 text-sm"
                  >
                    <span className="font-medium text-ink-900">{s.student_name}</span>
                    <span className="flex items-center gap-3">
                      {settled && s.total_final !== null ? (
                        <span className="tabular-nums text-ink-700">
                          {s.total_final}/{s.total_max}
                        </span>
                      ) : (
                        <span
                          className={`rounded-full px-2 py-0.5 text-xs font-medium ${badge.classes}`}
                        >
                          {badge.label}
                        </span>
                      )}
                      <Link
                        to={`/tutor/submissions/${s.id}`}
                        aria-label={`${needsTutor ? "Review" : "View"} ${s.student_name}'s work`}
                        className={buttonClasses(needsTutor ? "secondary" : "ghost", "sm")}
                      >
                        {needsTutor ? "Review" : "View"}
                      </Link>
                    </span>
                  </li>
                );
              })}
            </ul>
          ) : (
            <EmptyState
              title="No submissions yet"
              hint="Work appears here as students hand it in."
            />
          )}
        </SectionCard>
      )}
    </div>
  );
}
