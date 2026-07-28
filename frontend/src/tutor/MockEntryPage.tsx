import { useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import { getGroup } from "../api/groups";
import { createAssessment } from "../api/readiness";
import { ApiError } from "../api/client";
import { Button, Card, CardHeader, Field, Input, Select } from "../ui";

export default function MockEntryPage() {
  const { groupId } = useParams();
  const id = Number(groupId);
  const navigate = useNavigate();
  const group = useQuery({ queryKey: ["group", id], queryFn: () => getGroup(id) });

  const [meta, setMeta] = useState({
    title: "",
    type: "mock",
    date: new Date().toISOString().slice(0, 10),
    max_marks: 100,
  });
  // student_id -> marks (blank = skip that student)
  const [marks, setMarks] = useState<Record<number, string>>({});
  const [error, setError] = useState<string | null>(null);

  const save = useMutation({
    mutationFn: () => {
      const scores = Object.entries(marks)
        .filter(([, m]) => m !== "")
        .map(([sid, m]) => ({
          student_id: Number(sid),
          topic_id: null,
          marks: Number(m),
          max_marks: meta.max_marks,
        }));
      return createAssessment({
        subject_id: group.data!.subject.id,
        title: meta.title,
        type: meta.type,
        date: meta.date,
        scores,
      });
    },
    onSuccess: () => navigate(`/tutor/groups/${id}/analytics`),
    onError: (err) => setError(err instanceof ApiError ? err.message : String(err)),
  });

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    save.mutate();
  }

  return (
    <div className="max-w-2xl">
      <Link to={`/tutor/groups/${id}/analytics`} className="text-sm text-brand-600 hover:underline">
        ← Analytics
      </Link>
      <h2 className="mt-1 text-xl font-semibold text-slate-800">Record mock / test marks</h2>
      <p className="mt-1 text-sm text-slate-500">
        Enter each student's overall mark. These count as strong evidence in readiness.
      </p>

      <form onSubmit={onSubmit} className="mt-5 space-y-4">
        <Card>
          <div className="flex flex-wrap items-end gap-3 p-4">
            <Field label="Title" className="flex-1 basis-48">
              {(props) => (
                <Input
                  {...props}
                  placeholder="e.g. October Mock"
                  value={meta.title}
                  onChange={(e) => setMeta({ ...meta, title: e.target.value })}
                  required
                />
              )}
            </Field>
            <Field label="Type" className="basis-36">
              {(props) => (
                <Select
                  {...props}
                  options={[
                    { value: "mock", label: "Mock" },
                    { value: "test", label: "Test" },
                  ]}
                  value={meta.type}
                  onChange={(e) => setMeta({ ...meta, type: e.target.value })}
                />
              )}
            </Field>
            <Field label="Date" className="basis-40">
              {(props) => (
                <Input
                  {...props}
                  type="date"
                  value={meta.date}
                  onChange={(e) => setMeta({ ...meta, date: e.target.value })}
                  required
                />
              )}
            </Field>
            <Field label="Out of" className="basis-24">
              {(props) => (
                <Input
                  {...props}
                  type="number"
                  min={1}
                  value={meta.max_marks}
                  onChange={(e) => setMeta({ ...meta, max_marks: Number(e.target.value) })}
                  required
                />
              )}
            </Field>
          </div>
        </Card>

        <Card>
          <CardHeader title="Marks" />
          <ul className="divide-y divide-slate-100">
            {group.data?.members.map((m) => (
              <li key={m.id} className="flex items-center justify-between gap-3 px-5 py-2.5">
                <span className="text-sm text-slate-700">{m.name}</span>
                <div className="flex items-center gap-2 text-sm">
                  <Input
                    type="number"
                    min={0}
                    max={meta.max_marks}
                    className="w-24"
                    aria-label={`Mark for ${m.name}`}
                    value={marks[m.id] ?? ""}
                    onChange={(e) => setMarks({ ...marks, [m.id]: e.target.value })}
                  />
                  <span className="text-slate-400">/ {meta.max_marks}</span>
                </div>
              </li>
            ))}
            {group.data?.members.length === 0 && (
              <li className="px-5 py-3 text-sm text-slate-500">No students in this class.</li>
            )}
          </ul>
        </Card>

        {error && <p className="text-sm text-risk-600">{error}</p>}
        <Button type="submit" disabled={save.isPending}>
          {save.isPending ? "Saving…" : "Save marks"}
        </Button>
      </form>
    </div>
  );
}
