import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createGroup, listGroups, listSubjects } from "../api/groups";

export default function GroupsPage() {
  const queryClient = useQueryClient();
  const groups = useQuery({ queryKey: ["groups"], queryFn: listGroups });
  const subjects = useQuery({ queryKey: ["subjects"], queryFn: listSubjects });
  const [showForm, setShowForm] = useState(false);
  const [name, setName] = useState("");
  const [subjectId, setSubjectId] = useState<number | "">("");

  const create = useMutation({
    mutationFn: () => createGroup(name, subjectId as number),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["groups"] });
      setShowForm(false);
      setName("");
      setSubjectId("");
    },
  });

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (name && subjectId !== "") create.mutate();
  }

  return (
    <div>
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold text-slate-800">Your groups</h2>
        <button
          onClick={() => setShowForm((v) => !v)}
          className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
        >
          {showForm ? "Cancel" : "New group"}
        </button>
      </div>

      {showForm && (
        <form onSubmit={onSubmit} className="mt-4 flex flex-wrap items-end gap-3 rounded-lg border bg-white p-4">
          <div>
            <label className="block text-sm font-medium text-slate-700">Group name</label>
            <input
              className="mt-1 rounded-md border border-slate-300 px-3 py-2"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Chemistry — Year 10"
              required
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-700">Subject</label>
            <select
              className="mt-1 rounded-md border border-slate-300 px-3 py-2"
              value={subjectId}
              onChange={(e) => setSubjectId(Number(e.target.value))}
              required
            >
              <option value="" disabled>
                Choose a subject…
              </option>
              {subjects.data?.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.exam_board} {s.code} — {s.name}
                </option>
              ))}
            </select>
          </div>
          <button
            type="submit"
            disabled={create.isPending}
            className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          >
            Create
          </button>
          {create.isError && <p className="text-sm text-red-600">Could not create the group.</p>}
        </form>
      )}

      <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {groups.data?.map((g) => (
          <Link
            key={g.id}
            to={`/tutor/groups/${g.id}`}
            className="rounded-lg border bg-white p-4 hover:border-blue-400"
          >
            <div className="font-medium text-slate-800">{g.name}</div>
            <div className="mt-1 text-sm text-slate-500">
              {g.subject.exam_board} {g.subject.code} — {g.subject.name}
            </div>
            <div className="mt-2 text-sm text-slate-500">
              {g.member_count} student{g.member_count === 1 ? "" : "s"}
            </div>
          </Link>
        ))}
        {groups.data?.length === 0 && !showForm && (
          <p className="text-slate-500">No groups yet — create your first group to invite students.</p>
        )}
      </div>
    </div>
  );
}
