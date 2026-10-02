import { useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import { getGroup } from "../api/groups";
import { createAssessment } from "../api/readiness";
import { friendlyError } from "../lib/errors";
import { InitialsAvatar, SectionCard } from "../components/ui";
import { Button, Field, Input, Select, buttonClasses, inputClasses } from "../components/controls";
import { ErrorState, SectionSkeleton } from "../components/page";

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
    onError: (err) => setError(friendlyError(err, "Couldn't save the marks. Try again.")),
  });

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    save.mutate();
  }

  return (
    <div className="max-w-2xl">
      {/* Rendered inside the class layout, whose header already carries the
          page's one <h1> — so this screen opens on an <h2>. */}
      <Link
        to={`/tutor/groups/${id}`}
        className="inline-flex items-center gap-1 text-sm text-ink-500 transition-colors hover:text-brand-600"
      >
        <ArrowLeft aria-hidden className="h-3.5 w-3.5" />
        Back to class
      </Link>
      <h2 className="mt-2 text-xl text-ink-900">Record mock or test marks</h2>
      <p className="mt-1 text-sm text-ink-500">
        Enter each student's overall mark. These count as strong evidence in readiness. Leave a
        student blank if they didn't sit it.
      </p>

      <form onSubmit={onSubmit} className="mt-6 space-y-6">
        <SectionCard>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Title" className="sm:col-span-2">
              <Input
                placeholder="e.g. October mock"
                value={meta.title}
                onChange={(e) => setMeta({ ...meta, title: e.target.value })}
                required
              />
            </Field>
            <Field label="Type">
              <Select
                value={meta.type}
                onChange={(e) => setMeta({ ...meta, type: e.target.value })}
              >
                <option value="mock">Mock</option>
                <option value="test">Test</option>
              </Select>
            </Field>
            <Field label="Date">
              <Input
                type="date"
                value={meta.date}
                onChange={(e) => setMeta({ ...meta, date: e.target.value })}
                required
              />
            </Field>
            <Field label="Total marks available">
              <Input
                type="number"
                min={1}
                value={meta.max_marks}
                onChange={(e) => setMeta({ ...meta, max_marks: Number(e.target.value) })}
                required
              />
            </Field>
          </div>
        </SectionCard>

        <SectionCard>
          <h3 className="font-medium text-ink-900">Marks</h3>
          {group.isLoading ? (
            <div className="mt-3">
              <SectionSkeleton rows={3} label="Loading students" />
            </div>
          ) : group.isError ? (
            <div className="mt-3">
              <ErrorState
                title="The class list didn't load"
                error={group.error}
                onRetry={() => group.refetch()}
              />
            </div>
          ) : group.data && group.data.members.length > 0 ? (
            <ul className="mt-2 divide-y divide-line">
              {group.data.members.map((m) => (
                <li key={m.id} className="flex items-center justify-between gap-3 py-2.5">
                  <label
                    htmlFor={`mark-${m.id}`}
                    className="flex min-w-0 items-center gap-3 text-sm text-ink-900"
                  >
                    <InitialsAvatar name={m.name} size="sm" />
                    <span className="truncate">{m.name}</span>
                  </label>
                  <span className="flex items-center gap-2 text-sm">
                    <input
                      id={`mark-${m.id}`}
                      type="number"
                      min={0}
                      max={meta.max_marks}
                      className={`${inputClasses.replace("w-full", "")} w-24 tabular-nums`}
                      value={marks[m.id] ?? ""}
                      onChange={(e) => setMarks({ ...marks, [m.id]: e.target.value })}
                    />
                    <span className="w-12 text-ink-500">/ {meta.max_marks}</span>
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-2 text-sm text-ink-500">No students in this class yet.</p>
          )}
        </SectionCard>

        {error && (
          <p role="alert" className="text-sm text-risk-600">
            {error}
          </p>
        )}
        <div className="flex items-center gap-2">
          <Button type="submit" size="lg" loading={save.isPending} disabled={!group.data}>
            Save marks
          </Button>
          <Link to={`/tutor/groups/${id}`} className={buttonClasses("ghost", "lg")}>
            Cancel
          </Link>
        </div>
      </form>
    </div>
  );
}
