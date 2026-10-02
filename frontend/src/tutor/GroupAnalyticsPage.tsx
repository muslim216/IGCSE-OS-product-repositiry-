import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { groupAnalytics } from "../api/readiness";

function scoreColor(score: number): string {
  if (score >= 70) return "text-green-600";
  if (score >= 50) return "text-amber-600";
  return "text-red-600";
}

export default function GroupAnalyticsPage() {
  const { groupId } = useParams();
  const id = Number(groupId);
  const analytics = useQuery({
    queryKey: ["analytics", id],
    queryFn: () => groupAnalytics(id),
  });

  if (analytics.isLoading) return <p className="text-slate-500">Loading…</p>;
  const a = analytics.data;

  // Rendered as a tab inside GroupLayout, which already shows the class header.
  return (
    <div className="space-y-6">
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
              <p className="mt-2 text-sm text-slate-500">No AI-marked questions finalized yet.</p>
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
                      {t.includes_tutor_estimate && (
                        <span className="ml-1 text-xs text-ink-500">includes tutor estimate</span>
                      )}
                    </span>
                    <span className={scoreColor(t.avg_score)}>{Math.round(t.avg_score)}%</span>
                  </li>
                ))}
                {/* The list holds only topics at or below the tutor's weak
                    threshold — a 0–100 score, 60 unless the tutor changed it
                    (task 5.6) — filtered from the class means, which count
                    medium/high-confidence marks only. So empty has three
                    meanings, and each claim must be one the data supports
                    (PROD-2): means exist and none is weak; learners are scored
                    but no topic has a mean, so nothing was compared; or there
                    is nothing at all. */}
                {a.weak_topics.length === 0 && (
                  <li className="py-1.5 text-ink-500">
                    {a.topic_mean_count > 0
                      ? "No topic is at or below the weak threshold."
                      : a.weak_students.length > 0
                        ? "Not enough confident topic data yet."
                        : "No readiness data yet."}
                  </li>
                )}
              </ul>
              {/* A student's own weak topics also count low-confidence marks,
                  so the two lists can differ. */}
              {a.weak_topics.length > 0 && (
                <p className="mt-2 text-xs text-ink-500">
                  Class averages count medium- and high-confidence marks only.
                </p>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
