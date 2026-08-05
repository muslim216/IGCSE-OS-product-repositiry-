import { useState, type FormEvent } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createObservation, studentReadiness, topicEvidence } from "../api/readiness";
import { listTopics } from "../api/syllabus";
import { SubjectReadinessCard } from "../components/ReadinessView";
import { ReportsPanel } from "../components/ReportsPanel";

export default function StudentDetailPage() {
  const { studentId } = useParams();
  const sid = Number(studentId);
  const [params] = useSearchParams();
  const groupId = params.get("group");
  const subjectIdParam = params.get("subject");
  const queryClient = useQueryClient();

  const readiness = useQuery({
    queryKey: ["student-readiness", sid],
    queryFn: () => studentReadiness(sid),
  });
  const [selectedTopic, setSelectedTopic] = useState<number | null>(null);

  const evidence = useQuery({
    queryKey: ["topic-evidence", sid, selectedTopic],
    queryFn: () => topicEvidence(sid, selectedTopic!),
    enabled: selectedTopic !== null,
  });

  const subjectId = subjectIdParam
    ? Number(subjectIdParam)
    : readiness.data?.subjects[0]?.subject_id;
  const topics = useQuery({
    queryKey: ["topics", subjectId],
    queryFn: () => listTopics(subjectId!),
    enabled: subjectId !== undefined,
  });

  const [obs, setObs] = useState({ topic_id: "", comment: "", rating: "" });
  const addObservation = useMutation({
    mutationFn: () =>
      createObservation({
        student_id: sid,
        topic_id: obs.topic_id ? Number(obs.topic_id) : null,
        comment: obs.comment,
        rating: obs.rating ? Number(obs.rating) : null,
      }),
    onSuccess: () => {
      setObs({ topic_id: "", comment: "", rating: "" });
      queryClient.invalidateQueries({ queryKey: ["student-readiness", sid] });
    },
  });

  function onObserve(e: FormEvent) {
    e.preventDefault();
    if (obs.comment) addObservation.mutate();
  }

  if (readiness.isLoading) return <p className="text-slate-500">Loading…</p>;

  return (
    <div className="space-y-6">
      {groupId && (
        <Link to={`/tutor/groups/${groupId}`} className="text-sm text-blue-600 hover:underline">
          ← Back to group
        </Link>
      )}
      <h2 className="text-xl font-semibold text-slate-800">{readiness.data?.student_name}</h2>

      <div className="grid gap-4 lg:grid-cols-2">
        {readiness.data?.subjects.map((s) => (
          <SubjectReadinessCard key={s.subject_id} subject={s} onTopicClick={setSelectedTopic} />
        ))}
        {readiness.data?.subjects.length === 0 && (
          <p className="text-slate-500">No readiness data yet for this student.</p>
        )}
      </div>

      {selectedTopic !== null && evidence.data && (
        <div className="rounded-lg border bg-white p-4">
          <div className="flex items-center justify-between">
            <h3 className="font-medium text-slate-800">
              Evidence for {evidence.data.topic_code} {evidence.data.topic_title}
            </h3>
            <button
              onClick={() => setSelectedTopic(null)}
              className="text-sm text-slate-400 hover:text-slate-700"
            >
              Close
            </button>
          </div>
          <p className="mt-1 text-sm text-slate-500">
            Readiness {Math.round(evidence.data.score)}% ({evidence.data.confidence} confidence) —
            every score is explainable by the evidence below.
          </p>
          <ul className="mt-2 divide-y text-sm">
            {evidence.data.evidence.map((e, i) => (
              <li key={i} className="flex items-center justify-between py-1.5">
                <span className="text-slate-600">
                  {e.label ?? e.source_type}{" "}
                  <span className="text-xs text-slate-400">({e.source_type})</span>
                </span>
                <span className="flex items-center gap-3 text-slate-500">
                  <span>{Math.round(e.score_pct)}%</span>
                  <span className="text-xs text-slate-400">
                    {new Date(e.occurred_at).toLocaleDateString()}
                  </span>
                </span>
              </li>
            ))}
            {evidence.data.evidence.length === 0 && (
              <li className="py-1.5 text-slate-500">No evidence yet.</li>
            )}
          </ul>
        </div>
      )}

      <ReportsPanel studentId={sid} audiences={["student", "tutor", "parent"]} />

      <div className="rounded-lg border bg-white p-4">
        <h3 className="font-medium text-slate-800">Add an observation</h3>
        <p className="mt-1 text-sm text-slate-500">
          A rating on a topic feeds into readiness as your professional judgement.
        </p>
        <form onSubmit={onObserve} className="mt-3 space-y-3">
          <div className="flex flex-wrap gap-2">
            <select
              className="rounded border border-slate-300 px-3 py-2 text-sm"
              value={obs.topic_id}
              onChange={(e) => setObs({ ...obs, topic_id: e.target.value })}
            >
              <option value="">General (no topic)</option>
              {topics.data?.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.code} {t.title}
                </option>
              ))}
            </select>
            <input
              type="number"
              min={0}
              max={100}
              placeholder="Rating 0–100"
              className="w-32 rounded border border-slate-300 px-3 py-2 text-sm"
              value={obs.rating}
              onChange={(e) => setObs({ ...obs, rating: e.target.value })}
            />
          </div>
          <textarea
            className="w-full rounded border border-slate-300 px-3 py-2 text-sm"
            rows={2}
            placeholder="What did you notice?"
            value={obs.comment}
            onChange={(e) => setObs({ ...obs, comment: e.target.value })}
            required
          />
          <button
            type="submit"
            disabled={addObservation.isPending}
            className="rounded-md bg-slate-700 px-3 py-2 text-sm text-white hover:bg-slate-800 disabled:opacity-50"
          >
            Save observation
          </button>
          {addObservation.isError && (
            <p className="text-sm text-red-600">Could not save the observation.</p>
          )}
        </form>
      </div>
    </div>
  );
}
