import { useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createObservation,
  studentReadiness,
  topicEvidence,
} from "../api/readiness";
import { listTopics } from "../api/syllabus";
import { SubjectReadinessCard } from "../components/ReadinessView";
import { ReportsPanel } from "../components/ReportsPanel";
import { useGroupContext } from "./GroupLayout";
import { Button, Field, Input, Select, Textarea } from "../ui";

export default function StudentDetailPage() {
  const { studentId } = useParams();
  const sid = Number(studentId);
  // The class (and so the subject) now comes from the route rather than a querystring.
  const { group, groupId } = useGroupContext();
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

  const subjectId = group.subject.id;
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
      <Link
        to={`/tutor/groups/${groupId}/students`}
        className="text-sm text-brand-600 hover:underline"
      >
        ← All students
      </Link>
      <h2 className="text-xl font-semibold text-slate-800">
        {readiness.data?.student_name}
      </h2>

      <div className="grid gap-4 lg:grid-cols-2">
        {readiness.data?.subjects.map((s) => (
          <SubjectReadinessCard
            key={s.subject_id}
            subject={s}
            onTopicClick={setSelectedTopic}
          />
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
          <div className="flex flex-wrap gap-3">
            <Field label="Topic" className="flex-1 basis-64">
              {(props) => (
                <Select
                  {...props}
                  value={obs.topic_id}
                  onChange={(e) => setObs({ ...obs, topic_id: e.target.value })}
                >
                  <option value="">General (no topic)</option>
                  {topics.data?.map((t) => (
                    <option key={t.id} value={t.id}>
                      {t.code} {t.title}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
            <Field label="Rating" hint="0–100, optional" className="basis-32">
              {(props) => (
                <Input
                  {...props}
                  type="number"
                  min={0}
                  max={100}
                  value={obs.rating}
                  onChange={(e) => setObs({ ...obs, rating: e.target.value })}
                />
              )}
            </Field>
          </div>
          <Field label="What did you notice?">
            {(props) => (
              <Textarea
                {...props}
                rows={2}
                value={obs.comment}
                onChange={(e) => setObs({ ...obs, comment: e.target.value })}
                required
              />
            )}
          </Field>
          <Button type="submit" disabled={addObservation.isPending}>
            {addObservation.isPending ? "Saving…" : "Save observation"}
          </Button>
          {addObservation.isError && (
            <p className="text-sm text-risk-600">Could not save the observation.</p>
          )}
        </form>
      </div>
    </div>
  );
}
