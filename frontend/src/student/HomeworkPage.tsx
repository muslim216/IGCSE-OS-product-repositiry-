import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { myAssignments } from "../api/homework";

const STATUS_BADGE: Record<string, { label: string; cls: string }> = {
  not_submitted: { label: "Not started", cls: "bg-slate-100 text-slate-600" },
  submitted: { label: "Submitted", cls: "bg-blue-100 text-blue-700" },
  being_marked: { label: "Being marked", cls: "bg-amber-100 text-amber-700" },
  marked: { label: "Marked", cls: "bg-green-100 text-green-700" },
};

function dueLabel(due: string | null): string {
  if (!due) return "No due date";
  const d = new Date(due);
  return `Due ${d.toLocaleDateString(undefined, { day: "numeric", month: "short" })}`;
}

export default function HomeworkPage() {
  const assignments = useQuery({ queryKey: ["my-assignments"], queryFn: myAssignments });

  return (
    <div>
      <h2 className="text-xl font-semibold text-slate-800">Your homework</h2>
      <div className="mt-4 space-y-3">
        {assignments.data?.map((a) => {
          const badge = STATUS_BADGE[a.submission_status ?? "not_submitted"];
          return (
            <Link
              key={a.id}
              to={`/student/homework/${a.id}`}
              className="flex items-center justify-between rounded-lg border bg-white p-4 hover:border-blue-400"
            >
              <div>
                <div className="font-medium text-slate-800">{a.title}</div>
                <div className="mt-1 text-sm text-slate-500">
                  {a.subject_name} · {a.question_count} questions · {a.total_marks} marks
                </div>
                <div className="mt-1 text-sm text-slate-400">{dueLabel(a.due_at)}</div>
              </div>
              <div className="flex items-center gap-3">
                {a.submission_status === "marked" && a.my_total !== null && (
                  <span className="text-sm font-medium text-slate-700">
                    {a.my_total}/{a.total_marks}
                  </span>
                )}
                <span className={`rounded-full px-2.5 py-1 text-xs ${badge.cls}`}>
                  {badge.label}
                </span>
              </div>
            </Link>
          );
        })}
        {assignments.data?.length === 0 && (
          <p className="text-slate-500">No homework yet — check back after your tutor sets some.</p>
        )}
      </div>
    </div>
  );
}
