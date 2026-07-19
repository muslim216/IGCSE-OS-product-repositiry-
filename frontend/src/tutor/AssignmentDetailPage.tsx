import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
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

interface EditableQuestion extends QuestionIn {
  key: number;
}

const STATUS_LABEL: Record<string, string> = {
  extracting: "AI is reading the booklet…",
  extraction_failed: "Extraction failed",
  review: "Review the questions, then publish",
  published: "Published",
  closed: "Closed",
};

export default function AssignmentDetailPage() {
  const { assignmentId } = useParams();
  const id = Number(assignmentId);
  const queryClient = useQueryClient();

  const assignment = useQuery({
    queryKey: ["assignment", id],
    queryFn: () => getAssignment(id),
    refetchInterval: (query) =>
      query.state.data?.status === "extracting" ? 2500 : false,
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
    mutationFn: () => replaceQuestions(id, rows.map(({ key, ...q }) => q)),
    onSuccess: () => {
      setDirty(false);
      queryClient.invalidateQueries({ queryKey: ["assignment", id] });
    },
    onError: (err) => setError(err instanceof ApiError ? err.message : String(err)),
  });
  const publish = useMutation({
    mutationFn: async () => {
      if (dirty) await replaceQuestions(id, rows.map(({ key, ...q }) => q));
      return publishAssignment(id);
    },
    onSuccess: () => {
      setDirty(false);
      queryClient.invalidateQueries({ queryKey: ["assignment", id] });
    },
    onError: (err) => setError(err instanceof ApiError ? err.message : String(err)),
  });
  const retry = useMutation({
    mutationFn: () => retryExtraction(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["assignment", id] }),
  });

  if (assignment.isLoading) return <p className="text-slate-500">Loading…</p>;
  if (assignment.isError || !assignment.data)
    return <p className="text-red-600">Assignment not found.</p>;
  const a = assignment.data;
  const editable = a.status === "review" || a.status === "extraction_failed";

  function update(key: number, patch: Partial<EditableQuestion>) {
    setRows((prev) => prev.map((r) => (r.key === key ? { ...r, ...patch } : r)));
    setDirty(true);
  }

  return (
    <div className="space-y-6">
      <div>
        <Link
          to={`/tutor/groups/${a.group_id}`}
          className="text-sm text-blue-600 hover:underline"
        >
          ← {group.data?.name ?? "Group"}
        </Link>
        <div className="mt-1 flex items-center gap-3">
          <h2 className="text-xl font-semibold text-slate-800">{a.title}</h2>
          <span
            className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${
              a.status === "published"
                ? "bg-green-100 text-green-700"
                : a.status === "extraction_failed"
                  ? "bg-red-100 text-red-700"
                  : "bg-amber-100 text-amber-700"
            }`}
          >
            {STATUS_LABEL[a.status] ?? a.status}
          </span>
        </div>
        {a.question_range && (
          <p className="text-sm text-slate-500">Range: {a.question_range}</p>
        )}
      </div>

      {a.status === "extracting" && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">
          The AI is reading the classified and building the question list — this usually takes
          under a minute. The page refreshes automatically.
        </div>
      )}

      {a.status === "extraction_failed" && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          <p className="font-medium">Extraction failed: {a.extraction_error}</p>
          <p className="mt-1">
            You can retry, or add the questions manually below and publish.
          </p>
          <button
            onClick={() => retry.mutate()}
            className="mt-2 rounded bg-red-600 px-3 py-1.5 text-white hover:bg-red-700"
          >
            Retry extraction
          </button>
        </div>
      )}

      {(editable || a.questions.length > 0) && a.status !== "extracting" && (
        <section className="rounded-lg border bg-white p-4">
          <div className="flex items-center justify-between">
            <h3 className="font-medium text-slate-800">
              Questions ({rows.length}) — total{" "}
              {rows.reduce((sum, r) => sum + (r.max_marks || 0), 0)} marks
            </h3>
            {editable && (
              <div className="flex gap-2">
                <button
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
                  className="rounded border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-50"
                >
                  Add question
                </button>
                <button
                  onClick={() => save.mutate()}
                  disabled={!dirty || save.isPending}
                  className="rounded bg-slate-700 px-3 py-1.5 text-sm text-white hover:bg-slate-800 disabled:opacity-40"
                >
                  Save changes
                </button>
                <button
                  onClick={() => publish.mutate()}
                  disabled={publish.isPending || rows.length === 0}
                  className="rounded bg-blue-600 px-3 py-1.5 text-sm text-white hover:bg-blue-700 disabled:opacity-40"
                >
                  Publish to students
                </button>
              </div>
            )}
          </div>
          {error && <p className="mt-2 text-sm text-red-600">{error}</p>}

          <table className="mt-3 w-full text-sm">
            <thead>
              <tr className="border-b text-left text-slate-500">
                <th className="py-1.5 pr-2 font-medium">Q#</th>
                <th className="py-1.5 pr-2 font-medium">Summary</th>
                <th className="py-1.5 pr-2 font-medium">Marks</th>
                <th className="py-1.5 pr-2 font-medium" title="Official mark scheme available">
                  MS?
                </th>
                <th className="py-1.5 font-medium">Topics</th>
                {editable && <th />}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.key} className="border-b align-top">
                  <td className="py-1.5 pr-2">
                    {editable ? (
                      <input
                        className="w-14 rounded border border-slate-300 px-1.5 py-1"
                        value={r.number}
                        onChange={(e) => update(r.key, { number: e.target.value })}
                      />
                    ) : (
                      r.number
                    )}
                  </td>
                  <td className="py-1.5 pr-2">
                    {editable ? (
                      <input
                        className="w-full rounded border border-slate-300 px-1.5 py-1"
                        value={r.text_summary}
                        onChange={(e) => update(r.key, { text_summary: e.target.value })}
                      />
                    ) : (
                      r.text_summary
                    )}
                  </td>
                  <td className="py-1.5 pr-2">
                    {editable ? (
                      <input
                        type="number"
                        min={1}
                        className="w-16 rounded border border-slate-300 px-1.5 py-1"
                        value={r.max_marks}
                        onChange={(e) => update(r.key, { max_marks: Number(e.target.value) })}
                      />
                    ) : (
                      r.max_marks
                    )}
                  </td>
                  <td className="py-1.5 pr-2">
                    {editable ? (
                      <input
                        type="checkbox"
                        checked={r.has_mark_scheme}
                        onChange={(e) => update(r.key, { has_mark_scheme: e.target.checked })}
                        title="AI only marks questions with an official mark scheme"
                      />
                    ) : r.has_mark_scheme ? (
                      "✓"
                    ) : (
                      <span className="text-amber-600" title="You will mark this question yourself">
                        you
                      </span>
                    )}
                  </td>
                  <td className="py-1.5">
                    {editable ? (
                      <select
                        multiple
                        size={2}
                        className="w-full rounded border border-slate-300 px-1.5 py-1"
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
                            {t.code} {t.title}
                          </option>
                        ))}
                      </select>
                    ) : (
                      topics.data
                        ?.filter((t) => r.topic_ids.includes(t.id))
                        .map((t) => t.code)
                        .join(", ")
                    )}
                  </td>
                  {editable && (
                    <td className="py-1.5 pl-2">
                      <button
                        onClick={() => {
                          setRows((prev) => prev.filter((x) => x.key !== r.key));
                          setDirty(true);
                        }}
                        className="text-red-500 hover:underline"
                      >
                        ✕
                      </button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {(a.status === "published" || a.status === "closed") && (
        <section className="rounded-lg border bg-white p-4">
          <h3 className="font-medium text-slate-800">Submissions</h3>
          <ul className="mt-2 divide-y">
            {submissions.data?.map((s) => (
              <li key={s.id} className="flex items-center justify-between py-2 text-sm">
                <span className="font-medium text-slate-700">{s.student_name}</span>
                <span className="flex items-center gap-3">
                  {s.status === "finalized" ? (
                    <span className="text-slate-600">
                      {s.total_final}/{s.total_max}
                    </span>
                  ) : (
                    <span
                      className={`rounded-full px-2 py-0.5 text-xs ${
                        s.status === "ai_marked"
                          ? "bg-blue-100 text-blue-700"
                          : s.status === "ai_failed"
                            ? "bg-red-100 text-red-700"
                            : "bg-slate-100 text-slate-600"
                      }`}
                    >
                      {s.status === "ai_marked"
                        ? "AI draft ready"
                        : s.status === "ai_failed"
                          ? "AI failed — mark manually"
                          : s.status}
                    </span>
                  )}
                  <Link
                    to={`/tutor/submissions/${s.id}`}
                    className="text-blue-600 hover:underline"
                  >
                    {s.status === "finalized" ? "View" : "Review"}
                  </Link>
                </span>
              </li>
            ))}
            {submissions.data?.length === 0 && (
              <li className="py-2 text-sm text-slate-500">No submissions yet.</li>
            )}
          </ul>
        </section>
      )}
    </div>
  );
}
