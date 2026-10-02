import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ChevronRight, Plus } from "lucide-react";
import { listGroupAssignments } from "../../api/homework";
import { useGroupContext } from "../GroupLayout";
import { EmptyState, SectionCard } from "../../components/ui";
import { buttonClasses } from "../../components/controls";
import { ErrorState, SectionSkeleton } from "../../components/page";
import { assignmentStatus } from "../../lib/assignmentStatus";

function StatusBadge({ status, submissionCount }: { status: string; submissionCount: number }) {
  if (status === "published")
    return (
      <span className="rounded-full bg-ok-100 px-2 py-0.5 text-xs font-medium text-ok-700">
        {submissionCount} handed in
      </span>
    );
  const known = assignmentStatus(status);
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${known.classes}`}>
      {known.label}
    </span>
  );
}

export default function HomeworkTab() {
  const { groupId } = useGroupContext();
  const assignments = useQuery({
    queryKey: ["assignments", groupId],
    queryFn: () => listGroupAssignments(groupId),
  });
  const newHomework = `/tutor/groups/${groupId}/new-homework`;

  if (assignments.isLoading) return <SectionSkeleton rows={4} label="Loading homework" />;

  // A failed load must not read as "no homework yet" — that invites the tutor
  // to re-create work that already exists.
  if (assignments.isError) {
    return (
      <ErrorState
        title="Couldn't load this class's homework"
        error={assignments.error}
        onRetry={() => assignments.refetch()}
      />
    );
  }

  if (assignments.data?.length === 0) {
    return (
      <SectionCard>
        <EmptyState
          title="No homework yet"
          hint="Upload a past paper or worksheet and the questions are pulled out automatically, ready for students to submit against."
          action={
            <Link to={newHomework} className={buttonClasses("primary", "md")}>
              <Plus aria-hidden className="h-4 w-4" />
              Set homework
            </Link>
          }
        />
      </SectionCard>
    );
  }

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-lg text-ink-900">Homework</h2>
        <Link to={newHomework} className={buttonClasses("primary", "sm")}>
          <Plus aria-hidden className="h-4 w-4" />
          Set homework
        </Link>
      </div>

      <ul className="mt-4 divide-y divide-line overflow-hidden rounded-xl border border-line bg-surface">
        {assignments.data?.map((a) => (
          <li key={a.id}>
            <Link
              to={`/tutor/assignments/${a.id}`}
              className="flex items-center justify-between gap-3 px-5 py-3.5 transition-colors hover:bg-surface-muted"
            >
              <span className="min-w-0">
                <span className="block truncate font-medium text-ink-900">{a.title}</span>
                <span className="text-sm text-ink-500">
                  {a.total_marks} {a.total_marks === 1 ? "mark" : "marks"}
                </span>
              </span>
              <span className="flex shrink-0 items-center gap-2">
                <StatusBadge status={a.status} submissionCount={a.submission_count} />
                <ChevronRight aria-hidden className="h-4 w-4 text-ink-500" />
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
