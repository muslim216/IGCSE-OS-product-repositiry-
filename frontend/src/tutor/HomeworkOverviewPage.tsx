import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { listGroups } from "../api/groups";
import { assignmentsNeedingAttention, reviewQueue } from "../api/homework";

const REASON_LABELS: Record<string, string> = {
  extraction_failed: "Question extraction failed",
  ai_failed: "AI marking failed",
  ai_marked: "AI-marked — awaiting your review",
  needs_review: "Some marks need your decision",
};

export default function HomeworkOverviewPage() {
  const groups = useQuery({ queryKey: ["groups"], queryFn: listGroups });
  const attention = useQuery({
    queryKey: ["assignments-attention"],
    queryFn: assignmentsNeedingAttention,
  });
  const queue = useQuery({ queryKey: ["review-queue"], queryFn: reviewQueue });

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold text-slate-800">Homework</h2>
        <p className="text-sm text-slate-500">
          Homework is marked automatically. You only review the marks the AI wasn't sure about, plus
          anything a student has asked you to look at again.
        </p>
      </div>

      <div className="rounded-lg border bg-white p-4">
        <div className="flex items-center gap-2">
          <h3 className="font-medium text-slate-800">Needs review</h3>
          {queue.data && queue.data.length > 0 && (
            <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-800">
              {queue.data.length}
            </span>
          )}
        </div>
        <ul className="mt-2 divide-y text-sm">
          {queue.data?.map((item) => (
            <li key={item.submission_id} className="flex items-center justify-between py-2">
              <div>
                <Link
                  to={`/tutor/submissions/${item.submission_id}`}
                  className="text-blue-600 hover:underline"
                >
                  {item.assignment_title}
                </Link>
                {item.past_paper_id && (
                  <span className="ml-2 rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-600">
                    Past paper
                  </span>
                )}
                <span className="ml-2 text-slate-500">— {item.student_name}</span>
              </div>
              <div className="flex gap-2 text-xs">
                {item.unsure_count > 0 && (
                  <span className="rounded bg-amber-50 px-2 py-0.5 text-amber-800">
                    {item.unsure_count} unsure
                  </span>
                )}
                {item.remark_request_count > 0 && (
                  <span className="rounded bg-purple-50 px-2 py-0.5 text-purple-800">
                    {item.remark_request_count} remark request
                    {item.remark_request_count > 1 ? "s" : ""}
                  </span>
                )}
              </div>
            </li>
          ))}
          {queue.data?.length === 0 && (
            <li className="py-2 text-slate-500">
              Nothing to review — everything was marked confidently.
            </li>
          )}
        </ul>
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
                {a.student_name && <span className="ml-2 text-slate-500">— {a.student_name}</span>}
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
