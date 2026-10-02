import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarClock, ClipboardList, Plus, Users } from "lucide-react";
import { createGroup, listGroups, listSubjects, type Group } from "../api/groups";
import { formatSlot } from "../lib/schedule";
import { friendlyError } from "../lib/errors";
import { EmptyState, SectionCard } from "../components/ui";
import { Button, Field, Input, Select } from "../components/controls";
import { ErrorState, PageHeader, Skeleton } from "../components/page";

function plural(n: number, one: string, many: string): string {
  return `${n} ${n === 1 ? one : many}`;
}

function ClassCard({ group }: { group: Group }) {
  return (
    <Link
      to={`/tutor/groups/${group.id}`}
      className="group flex flex-col gap-4 rounded-xl border border-line bg-surface p-5 shadow-[0_1px_2px_rgba(44,26,14,0.06)] transition hover:border-brand-600"
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate font-medium text-ink-900 group-hover:text-brand-600">
            {group.name}
          </p>
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

      <div className="mt-auto flex flex-wrap items-center gap-x-4 gap-y-1.5 text-sm text-ink-500">
        <span className="flex items-center gap-1.5">
          <Users aria-hidden className="h-4 w-4" />
          {plural(group.member_count, "student", "students")}
        </span>
        <span className="flex items-center gap-1.5">
          <ClipboardList aria-hidden className="h-4 w-4" />
          {plural(group.published_assignment_count, "piece of homework", "pieces of homework")}
        </span>
        {group.next_lesson && (
          <span className="flex items-center gap-1.5 text-brand-600">
            <CalendarClock aria-hidden className="h-4 w-4" />
            Next lesson {formatSlot(group.next_lesson.weekday, group.next_lesson.start_time)}
          </span>
        )}
      </div>
    </Link>
  );
}

function ClassCardsSkeleton() {
  return (
    <div
      role="status"
      aria-label="Loading classes"
      className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3"
    >
      {Array.from({ length: 3 }, (_, i) => (
        <div key={i} className="rounded-xl border border-line bg-surface p-5">
          <Skeleton className="h-5 w-2/3" />
          <Skeleton className="mt-2 h-4 w-1/2" />
          <Skeleton className="mt-6 h-4 w-3/4" />
        </div>
      ))}
    </div>
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
      closeForm();
    },
  });

  function closeForm() {
    setShowForm(false);
    setName("");
    setSubjectId("");
    create.reset();
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (name && subjectId !== "") create.mutate();
  }

  return (
    <div>
      <PageHeader
        title="Your classes"
        description="Each class is one subject with its own students, homework and timetable. Open one to see how it's doing."
        actions={
          !showForm && (
            <Button onClick={() => setShowForm(true)}>
              <Plus aria-hidden className="h-4 w-4" />
              New class
            </Button>
          )
        }
      />

      {showForm && (
        <SectionCard className="mb-6">
          <form onSubmit={onSubmit}>
            <h2 className="text-lg text-ink-900">New class</h2>
            <div className="mt-4 grid gap-4 sm:grid-cols-2">
              <Field label="Class name">
                <Input
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="e.g. Chemistry — Year 10"
                  required
                  autoFocus
                />
              </Field>
              {/* Retried in place: a refresh would also throw away the class
                  name already typed beside it. */}
              <div>
                <Field label="Subject" error={subjects.isError ? "Subjects didn't load." : null}>
                  <Select
                    value={subjectId}
                    onChange={(e) => setSubjectId(Number(e.target.value))}
                    required
                  >
                    <option value="" disabled>
                      {subjects.isLoading ? "Loading subjects…" : "Choose a subject"}
                    </option>
                    {subjects.data?.map((s) => (
                      <option key={s.id} value={s.id}>
                        {s.name} — {s.exam_board} {s.code}
                      </option>
                    ))}
                  </Select>
                </Field>
                {subjects.isError && (
                  <Button
                    variant="secondary"
                    size="sm"
                    className="mt-2"
                    loading={subjects.isFetching}
                    onClick={() => subjects.refetch()}
                  >
                    Try again
                  </Button>
                )}
              </div>
            </div>
            {create.isError && (
              <p role="alert" className="mt-3 text-sm text-risk-600">
                {friendlyError(create.error, "Couldn't create the class. Try again.")}
              </p>
            )}
            <div className="mt-5 flex justify-end gap-2">
              <Button variant="ghost" onClick={closeForm} disabled={create.isPending}>
                Cancel
              </Button>
              <Button type="submit" loading={create.isPending}>
                Create class
              </Button>
            </div>
          </form>
        </SectionCard>
      )}

      {groups.isLoading ? (
        <ClassCardsSkeleton />
      ) : groups.isError ? (
        <ErrorState
          title="Your classes didn't load"
          error={groups.error}
          onRetry={() => groups.refetch()}
        />
      ) : groups.data && groups.data.length > 0 ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {groups.data.map((g) => (
            <ClassCard key={g.id} group={g} />
          ))}
        </div>
      ) : (
        !showForm && (
          <SectionCard>
            <EmptyState
              title="No classes yet"
              hint="Create your first class, then invite students or add accounts for them."
              action={
                <Button onClick={() => setShowForm(true)}>
                  <Plus aria-hidden className="h-4 w-4" />
                  New class
                </Button>
              }
            />
          </SectionCard>
        )
      )}
    </div>
  );
}
