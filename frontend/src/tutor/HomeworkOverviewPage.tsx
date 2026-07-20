import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { listGroups } from "../api/groups";
import { assignmentsNeedingAttention } from "../api/homework";

const REASON_LABELS: Record<string, string> = {
  extraction_failed: "Question extraction failed",
  ai_failed: "AI marking failed",
  ai_marked: "AI-marked — awaiting your review",
};

export default function HomeworkOverviewPage() {
  const groups = useQuery({ queryKey: ["groups"], queryFn: listGroups });
  const attention = useQuery({
    queryKey: ["assignments-attention"],
    queryFn: assignmentsNeedingAttention,
  });

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold text-slate-800">Homework</h2>
        <p className="text-sm text-slate-500">
          Upload homework per group, and review anything flagged for your attention.
        </p>
      </div>

      <div className="rounded-lg border bg-white p-4">
        <h3 className="font-medium text-slate-800">Needs your attention</h3>
        <ul className="mt-2 divide-y text-sm">
          {attention.data?.map((a, i) => (
            <li key={i} className="flex items-center justify-between py-2">
              <div>
                <Link
                  to={
                    a.submission_id
                      ? `/tutor/submissions/${a.submission_id}`
                      : `/tutor/assignments/${a.assignment_id}`
                  }
                  className="text-blue-600 hover:underline"
                >
                  {a.assignment_title}
                </Link>
                {a.student_name && (
                  <span className="ml-2 text-slate-500">— {a.student_name}</span>
                )}
              </div>
              <span className="text-amber-700">{REASON_LABELS[a.reason] ?? a.reason}</span>
            </li>
          ))}
          {attention.data?.length === 0 && (
            <li className="py-2 text-slate-500">Nothing needs attention right now.</li>
          )}
        </ul>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {groups.data?.map((g) => (
          <div key={g.id} className="rounded-lg border bg-white p-4">
            <div className="font-medium text-slate-800">{g.name}</div>
            <div className="mt-1 text-sm text-slate-500">
              {g.subject.exam_board} {g.subject.code}
            </div>
            <Link
              to={`/tutor/groups/${g.id}/new-homework`}
              className="mt-2 inline-block text-sm text-blue-600 hover:underline"
            >
              New homework →
            </Link>
          </div>
        ))}
      </div>
    </div>
  );
}
