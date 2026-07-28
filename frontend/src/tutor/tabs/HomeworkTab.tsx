import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { listGroupAssignments } from "../../api/homework";
import { useGroupContext } from "../GroupLayout";
import { Badge, ButtonLink, Card, EmptyState } from "../../ui";

function statusBadge(status: string, submissionCount: number) {
  if (status === "published") return <Badge tone="ready">{submissionCount} submitted</Badge>;
  if (status === "extraction_failed") return <Badge tone="risk">extraction failed</Badge>;
  return <Badge tone="caution">{status.replace("_", " ")}</Badge>;
}

export default function HomeworkTab() {
  const { groupId } = useGroupContext();
  const assignments = useQuery({
    queryKey: ["assignments", groupId],
    queryFn: () => listGroupAssignments(groupId),
  });

  if (assignments.data?.length === 0) {
    return (
      <EmptyState
        icon="📄"
        title="No homework yet"
        description="Upload a past paper or worksheet and the questions are pulled out automatically, ready for students to submit against."
        action={{ label: "Set homework", to: `/tutor/groups/${groupId}/homework/new` }}
      />
    );
  }

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="font-semibold text-slate-900">Homework</h3>
        <div className="flex gap-2">
          <ButtonLink to={`/tutor/groups/${groupId}/classroom`} variant="secondary">
            Import from Classroom
          </ButtonLink>
          <ButtonLink to={`/tutor/groups/${groupId}/homework/new`} variant="primary">
            Set homework
          </ButtonLink>
        </div>
      </div>

      <Card className="mt-4">
        <ul className="divide-y divide-slate-100">
          {assignments.data?.map((a) => (
            <li key={a.id}>
              <Link
                to={`/tutor/groups/${groupId}/homework/${a.id}`}
                className="flex items-center justify-between gap-3 px-5 py-3 hover:bg-surface-muted"
              >
                <span className="min-w-0">
                  <span className="block truncate font-medium text-slate-800">{a.title}</span>
                  <span className="text-sm text-slate-500">{a.total_marks} marks</span>
                </span>
                {statusBadge(a.status, a.submission_count)}
              </Link>
            </li>
          ))}
        </ul>
      </Card>
    </div>
  );
}
