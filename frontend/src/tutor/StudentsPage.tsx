import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ChevronRight } from "lucide-react";
import { listMyStudents, type TutorStudent } from "../api/students";
import { Field, Input } from "../components/controls";
import { ErrorState, PageHeader, SectionSkeleton } from "../components/page";
import { EmptyState, SectionCard } from "../components/ui";

const linkClass = "font-medium text-brand-600 hover:text-brand-700";

function plural(n: number, one: string, many: string): string {
  return `${n} ${n === 1 ? one : many}`;
}

function StudentRow({ student }: { student: TutorStudent }) {
  return (
    <li>
      <Link
        to={`/tutor/students/${student.id}`}
        className="flex items-center justify-between gap-3 px-5 py-3.5 transition-colors hover:bg-surface-muted"
      >
        <span className="min-w-0">
          <span className="block truncate font-medium text-ink-900">{student.name}</span>
          <span className="block break-words text-sm text-ink-500">
            {student.classes.map((c) => c.group_name).join(", ")}
          </span>
        </span>
        <ChevronRight aria-hidden className="h-4 w-4 shrink-0 text-ink-500" />
      </Link>
    </li>
  );
}

export default function StudentsPage() {
  const students = useQuery({ queryKey: ["students", "mine"], queryFn: listMyStudents });
  const [search, setSearch] = useState("");

  // Derived from the query, never copied out of it (FE-6).
  const needle = search.trim().toLowerCase();
  const shown = useMemo(
    () =>
      (students.data?.items ?? []).filter((s) => !needle || s.name.toLowerCase().includes(needle)),
    [students.data, needle],
  );
  const total = students.data?.items.length ?? 0;

  return (
    <div>
      <PageHeader title="Students" description="Everyone in your classes, in one list." />
      {students.isLoading ? (
        <SectionSkeleton rows={5} label="Loading students" />
      ) : students.isError ? (
        // A failed load must not read as "no students yet".
        <ErrorState
          title="Couldn't load your students"
          error={students.error}
          onRetry={() => students.refetch()}
        />
      ) : total === 0 ? (
        <SectionCard>
          <EmptyState
            title="No students yet"
            hint="Students join through a class invite."
            action={
              <Link to="/tutor/classes" className={linkClass}>
                Go to Classes
              </Link>
            }
          />
        </SectionCard>
      ) : (
        <>
          <div className="mb-4 max-w-sm">
            <Field label="Search students">
              <Input
                type="search"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search by name"
              />
            </Field>
          </div>
          <p role="status" aria-live="polite" className="sr-only">
            {needle ? plural(shown.length, "student matches", "students match") : ""}
          </p>
          {shown.length === 0 ? (
            <SectionCard>
              <EmptyState
                title="No students match that name"
                hint="Check the spelling or clear the search."
              />
            </SectionCard>
          ) : (
            <ul className="divide-y divide-line overflow-hidden rounded-xl border border-line bg-surface">
              {shown.map((s) => (
                <StudentRow key={s.id} student={s} />
              ))}
            </ul>
          )}
          {students.data?.truncated && (
            <p className="mt-3 text-xs text-ink-500">
              Showing the first {students.data.limit} students by name. Others are in their
              class&apos;s Students tab.
            </p>
          )}
        </>
      )}
    </div>
  );
}
