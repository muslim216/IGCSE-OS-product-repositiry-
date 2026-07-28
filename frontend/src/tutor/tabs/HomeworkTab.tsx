import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { listGroupAssignments } from "../../api/homework";
import { useGroupContext } from "../GroupLayout";
import { EmptyState } from "../../components/ui";

function StatusBadge({ status, submissionCount }: { status: string; submissionCount: number }) {
  if (status === "published")
    return (
      <span className="rounded-full bg-green-100 px-2 py-0.5 text-xs text-green-700">
        {submissionCount} submitted
      </span>
    );
  if (status === "extraction_failed")
    return (
      <span className="rounded-full bg-red-100 px-2 py-0.5 text-xs text-red-700">
        extraction failed
      </span>
    );
  return (
    <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs text-amber-700">
      {status.replace("_", " ")}
    </span>
  );
}

export default function HomeworkTab() {
  const { groupId } = useGroupContext();
  const assignments = useQuery({
    queryKey: ["assignments", groupId],
    queryFn: () => listGroupAssignments(groupId),
  });

  // A failed load must not read as "no homework yet" — that invites the tutor
  // to re-create work that already exists.
  if (assignments.isError) {
    return (
      <EmptyState
        title="Couldn't load this class's homework"
        hint="The connection may have dropped."
        action={
          <button
            type="button"
            onClick={() => assignments.refetch()}
            className="rounded-md bg-brand-600 px-3 py-1.5 font-medium hover:bg-brand-700"
          >
            Try again
          </button>
        }
      />
    );
  }

  if (assignments.data?.length === 0) {
    return (
      <EmptyState
        title="No homework yet"
        hint="Upload a past paper or worksheet and the questions are pulled out automatically, ready for students to submit against."
        action={
          <Link
            to={`/tutor/groups/${groupId}/new-homework`}
            className="rounded-md bg-brand-600 px-3 py-1.5 font-medium hover:bg-brand-700"
          >
            Set homework
          </Link>
        }
      />
    );
  }

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="font-medium">Homework</h3>
        <Link
          to={`/tutor/groups/${groupId}/new-homework`}
          className="rounded-md bg-brand-600 px-3 py-1.5 text-sm font-medium hover:bg-brand-700"
        >
          Set homework
        </Link>
      </div>

      <ul className="mt-4 divide-y rounded-xl border border-line bg-surface">
        {assignments.data?.map((a) => (
          <li key={a.id}>
            <Link
              to={`/tutor/assignments/${a.id}`}
              className="flex items-center justify-between gap-3 px-5 py-3 hover:bg-slate-50"
            >
              <span className="min-w-0">
                <span className="block truncate font-medium text-ink-900">{a.title}</span>
                <span className="text-sm text-ink-500">{a.total_marks} marks</span>
              </span>
              <StatusBadge status={a.status} submissionCount={a.submission_count} />
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
