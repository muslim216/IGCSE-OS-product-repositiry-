import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarClock, ClipboardList, Users } from "lucide-react";
import { createGroup, listGroups, listSubjects, type Group } from "../api/groups";
import { formatSlot } from "../lib/schedule";
import { EmptyState } from "../components/ui";

function ClassCard({ group }: { group: Group }) {
  return (
    <Link
      to={`/tutor/groups/${group.id}`}
      className="group flex flex-col gap-3 rounded-xl border border-line bg-surface p-5 shadow-[0_1px_2px_rgba(44,26,14,0.06)] transition hover:border-brand-600"
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate font-medium text-ink-900">{group.name}</p>
          <p className="mt-0.5 truncate text-sm text-ink-500">
            {group.subject.exam_board} {group.subject.code} · {group.subject.name}
          </p>
        </div>
        {group.awaiting_review_count > 0 && (
          <span className="shrink-0 rounded-full bg-warn-100 px-2 py-0.5 text-xs font-medium text-warn-700">
            {group.awaiting_review_count} to review
          </span>
        )}
      </div>

      <div className="mt-auto flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-ink-500">
        <span className="flex items-center gap-1.5">
          <Users aria-hidden className="h-4 w-4" />
          {group.member_count} student{group.member_count === 1 ? "" : "s"}
        </span>
        <span className="flex items-center gap-1.5">
          <ClipboardList aria-hidden className="h-4 w-4" />
          {group.published_assignment_count} homework
        </span>
        {group.next_lesson && (
          <span className="flex items-center gap-1.5 text-brand-600">
            <CalendarClock aria-hidden className="h-4 w-4" />
            Next {formatSlot(group.next_lesson.weekday, group.next_lesson.start_time)}
          </span>
        )}
      </div>
    </Link>
  );
}

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
        <h2 className="text-xl font-semibold">Your classes</h2>
        <button
          onClick={() => setShowForm((v) => !v)}
          className="rounded-md bg-brand-600 px-4 py-2 text-sm font-medium hover:bg-brand-700"
        >
          {showForm ? "Cancel" : "New class"}
        </button>
      </div>

      {showForm && (
        <form
          onSubmit={onSubmit}
          className="mt-4 flex flex-wrap items-end gap-3 rounded-xl border border-line bg-surface p-4"
        >
          <div>
            <label className="block text-sm font-medium text-ink-700">Class name</label>
            <input
              className="mt-1 rounded-md border border-line px-3 py-2"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Chemistry — Year 10"
              required
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-ink-700">Subject</label>
            <select
              className="mt-1 rounded-md border border-line px-3 py-2"
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
            className="rounded-md bg-brand-600 px-4 py-2 text-sm font-medium hover:bg-brand-700 disabled:opacity-50"
          >
            Create
          </button>
          {create.isError && <p className="text-sm text-risk-600">Could not create the class.</p>}
        </form>
      )}

      <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {groups.data?.map((g) => (
          <ClassCard key={g.id} group={g} />
        ))}
      </div>
      {groups.data?.length === 0 && !showForm && (
        <EmptyState
          title="No classes yet"
          hint="Create your first class, then invite students or add accounts for them."
          action={
            <button
              onClick={() => setShowForm(true)}
              className="rounded-md bg-brand-600 px-3 py-1.5 font-medium hover:bg-brand-700"
            >
              New class
            </button>
          }
        />
      )}
    </div>
  );
}
