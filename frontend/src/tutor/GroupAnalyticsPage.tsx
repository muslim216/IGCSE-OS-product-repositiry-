import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { getGroup } from "../api/groups";
import { groupAnalytics } from "../api/readiness";

function scoreColor(score: number): string {
  if (score >= 70) return "text-green-600";
  if (score >= 50) return "text-amber-600";
  return "text-red-600";
}

export default function GroupAnalyticsPage() {
  const { groupId } = useParams();
  const id = Number(groupId);
  const group = useQuery({ queryKey: ["group", id], queryFn: () => getGroup(id) });
  const analytics = useQuery({
    queryKey: ["analytics", id],
    queryFn: () => groupAnalytics(id),
  });

  if (analytics.isLoading) return <p className="text-slate-500">Loading…</p>;
  const a = analytics.data;

  return (
    <div className="space-y-6">
      <div>
        <Link to={`/tutor/groups/${id}`} className="text-sm text-blue-600 hover:underline">
          ← {group.data?.name ?? "Group"}
        </Link>
        <h2 className="mt-1 text-xl font-semibold text-slate-800">Analytics</h2>
      </div>

      {a && (
        <>
          <div className="rounded-lg border bg-white p-4">
            <h3 className="font-medium text-slate-800">AI marking agreement</h3>
            <p className="mt-1 text-sm text-slate-500">
              How often your final marks matched the AI's first pass, on finalized homework.
            </p>
            {a.agreement.agreement_rate !== null ? (
              <p className="mt-2 text-2xl font-bold text-slate-800">
                {a.agreement.agreement_rate}%{" "}
                <span className="text-sm font-normal text-slate-500">
                  ({a.agreement.ai_agreed}/{a.agreement.total_marked_questions} questions)
                </span>
              </p>
            ) : (
              <p className="mt-2 text-sm text-slate-500">
                No AI-marked questions finalized yet.
              </p>
            )}
          </div>

          <div className="grid gap-4 md:grid-cols-2">
            <div className="rounded-lg border bg-white p-4">
              <h3 className="font-medium text-slate-800">Students needing attention</h3>
              <ul className="mt-2 divide-y text-sm">
                {a.weak_students.map((s) => (
                  <li key={s.student_id} className="flex items-center justify-between py-1.5">
                    <Link
                      to={`/tutor/students/${s.student_id}?group=${id}`}
                      className="text-blue-600 hover:underline"
                    >
                      {s.student_name}
                    </Link>
                    <span className={scoreColor(s.score)}>{Math.round(s.score)}%</span>
                  </li>
                ))}
                {a.weak_students.length === 0 && (
                  <li className="py-1.5 text-slate-500">No readiness data yet.</li>
                )}
              </ul>
            </div>

            <div className="rounded-lg border bg-white p-4">
              <h3 className="font-medium text-slate-800">Weakest topics (class average)</h3>
              <ul className="mt-2 divide-y text-sm">
                {a.weak_topics.map((t) => (
                  <li key={t.topic_code} className="flex items-center justify-between py-1.5">
                    <span className="text-slate-700">
                      {t.topic_code} {t.topic_title}
                    </span>
                    <span className={scoreColor(t.avg_score)}>
                      {Math.round(t.avg_score)}%
                    </span>
                  </li>
                ))}
                {a.weak_topics.length === 0 && (
                  <li className="py-1.5 text-slate-500">No readiness data yet.</li>
                )}
              </ul>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
