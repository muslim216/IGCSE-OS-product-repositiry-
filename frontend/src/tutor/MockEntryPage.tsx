import { useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import { getGroup } from "../api/groups";
import { createAssessment } from "../api/readiness";
import { ApiError } from "../api/client";

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
    onSuccess: () => navigate(`/tutor/groups/${id}`),
    onError: (err) => setError(err instanceof ApiError ? err.message : String(err)),
  });

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    save.mutate();
  }

  return (
    <div className="max-w-2xl">
      <Link to={`/tutor/groups/${id}`} className="text-sm text-blue-600 hover:underline">
        ← {group.data?.name ?? "Group"}
      </Link>
      <h2 className="mt-1 text-xl font-semibold text-slate-800">Record mock / test marks</h2>
      <p className="mt-1 text-sm text-slate-500">
        Enter each student's overall mark. These count as strong evidence in readiness.
      </p>

      <form onSubmit={onSubmit} className="mt-5 space-y-4">
        <div className="flex flex-wrap items-end gap-3 rounded-lg border bg-white p-4">
          <div>
            <label className="block text-sm font-medium text-slate-700">Title</label>
            <input
              className="mt-1 rounded border border-slate-300 px-3 py-2 text-sm"
              placeholder="e.g. October Mock"
              value={meta.title}
              onChange={(e) => setMeta({ ...meta, title: e.target.value })}
              required
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-700">Type</label>
            <select
              className="mt-1 rounded border border-slate-300 px-3 py-2 text-sm"
              value={meta.type}
              onChange={(e) => setMeta({ ...meta, type: e.target.value })}
            >
              <option value="mock">Mock</option>
              <option value="test">Test</option>
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-700">Date</label>
            <input
              type="date"
              className="mt-1 rounded border border-slate-300 px-3 py-2 text-sm"
              value={meta.date}
              onChange={(e) => setMeta({ ...meta, date: e.target.value })}
              required
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-700">Out of</label>
            <input
              type="number"
              min={1}
              className="mt-1 w-24 rounded border border-slate-300 px-3 py-2 text-sm"
              value={meta.max_marks}
              onChange={(e) => setMeta({ ...meta, max_marks: Number(e.target.value) })}
              required
            />
          </div>
        </div>

        <div className="rounded-lg border bg-white p-4">
          <h3 className="text-sm font-medium text-slate-700">Marks</h3>
          <ul className="mt-2 divide-y">
            {group.data?.members.map((m) => (
              <li key={m.id} className="flex items-center justify-between py-2">
                <span className="text-sm text-slate-700">{m.name}</span>
                <div className="flex items-center gap-1 text-sm">
                  <input
                    type="number"
                    min={0}
                    max={meta.max_marks}
                    className="w-20 rounded border border-slate-300 px-2 py-1"
                    value={marks[m.id] ?? ""}
                    onChange={(e) => setMarks({ ...marks, [m.id]: e.target.value })}
                  />
                  <span className="text-slate-400">/ {meta.max_marks}</span>
                </div>
              </li>
            ))}
            {group.data?.members.length === 0 && (
              <li className="py-2 text-sm text-slate-500">No students in this group.</li>
            )}
          </ul>
        </div>

        {error && <p className="text-sm text-red-600">{error}</p>}
        <button
          type="submit"
          disabled={save.isPending}
          className="rounded-md bg-blue-600 px-4 py-2 font-medium text-white hover:bg-blue-700 disabled:opacity-50"
        >
          {save.isPending ? "Saving…" : "Save marks"}
        </button>
      </form>
    </div>
  );
}
