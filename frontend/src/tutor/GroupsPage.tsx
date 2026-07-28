import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createGroup, listGroups, listSubjects } from "../api/groups";
import { GroupCard } from "./GroupCard";
import { Button, Card, EmptyState, Field, Input, Select } from "../ui";

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

  const isEmpty = groups.data?.length === 0;

  return (
    <div>
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-semibold text-slate-900">Your classes</h2>
          <p className="text-sm text-slate-500">
            Everything — homework, syllabus, schedule and progress — lives inside a class.
          </p>
        </div>
        <Button
          variant={showForm ? "secondary" : "primary"}
          onClick={() => setShowForm((v) => !v)}
        >
          {showForm ? "Cancel" : "New class"}
        </Button>
      </div>

      {showForm && (
        <Card className="mt-4">
          <form onSubmit={onSubmit} className="flex flex-wrap items-end gap-3 p-4">
            <Field label="Class name" className="flex-1 basis-56">
              {(props) => (
                <Input
                  {...props}
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="e.g. Chemistry — Year 10"
                  required
                />
              )}
            </Field>
            <Field label="Subject" className="flex-1 basis-64">
              {(props) => (
                <Select
                  {...props}
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
                </Select>
              )}
            </Field>
            <Button type="submit" disabled={create.isPending}>
              {create.isPending ? "Creating…" : "Create class"}
            </Button>
            {create.isError && (
              <p className="basis-full text-sm text-risk-600">Could not create the class.</p>
            )}
          </form>
        </Card>
      )}

      {isEmpty && !showForm ? (
        <EmptyState
          className="mt-6"
          icon="📚"
          title="Create your first class"
          description="A class holds your students, their homework, the syllabus you're covering and the weekly timetable. Once it exists you can invite students and set work."
          action={{ label: "New class", onClick: () => setShowForm(true) }}
        />
      ) : (
        <div className="mt-5 grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {groups.data?.map((g) => (
            <GroupCard key={g.id} group={g} />
          ))}
        </div>
      )}
    </div>
  );
}
