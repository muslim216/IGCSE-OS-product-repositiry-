import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { groupAnalytics } from "../../api/readiness";
import { useGroupContext } from "../GroupLayout";
import { ButtonLink, Card, CardBody, CardHeader, EmptyState } from "../../ui";

/** Matches the readiness thresholds used across the app (see ReadinessView). */
function scoreColor(score: number): string {
  if (score >= 70) return "text-ready-600";
  if (score >= 50) return "text-caution-600";
  return "text-risk-600";
}

export default function AnalyticsTab() {
  const { groupId } = useGroupContext();
  const analytics = useQuery({
    queryKey: ["analytics", groupId],
    queryFn: () => groupAnalytics(groupId),
  });

  if (analytics.isLoading) return <p className="text-slate-500">Loading…</p>;
  const a = analytics.data;
  if (!a) return <p className="text-risk-600">Could not load analytics.</p>;

  const hasReadiness = a.weak_students.length > 0 || a.weak_topics.length > 0;
  if (!hasReadiness && a.agreement.agreement_rate === null) {
    return (
      <EmptyState
        icon="📊"
        title="No analytics yet"
        description="Once homework and mocks are marked, this shows which students need attention and which topics the class finds hardest."
        action={{ label: "Record a mock", to: `/tutor/groups/${groupId}/mock` }}
      />
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h3 className="font-semibold text-slate-900">Class analytics</h3>
        <ButtonLink to={`/tutor/groups/${groupId}/mock`} variant="secondary">
          Record mock / test
        </ButtonLink>
      </div>

      <Card>
        <CardHeader
          title="AI marking agreement"
          description="How often your final marks matched the AI's first pass, on finalized homework."
        />
        <CardBody>
          {a.agreement.agreement_rate !== null ? (
            <p className="text-2xl font-bold text-slate-900">
              {a.agreement.agreement_rate}%{" "}
              <span className="text-sm font-normal text-slate-500">
                ({a.agreement.ai_agreed}/{a.agreement.total_marked_questions} questions)
              </span>
            </p>
          ) : (
            <p className="text-sm text-slate-500">No AI-marked questions finalized yet.</p>
          )}
        </CardBody>
      </Card>

      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader title="Students needing attention" />
          <CardBody className="pt-0">
            <ul className="divide-y divide-slate-100 text-sm">
              {a.weak_students.map((s) => (
                <li key={s.student_id} className="flex items-center justify-between py-2">
                  <Link
                    to={`/tutor/groups/${groupId}/students/${s.student_id}`}
                    className="text-brand-700 hover:underline"
                  >
                    {s.student_name}
                  </Link>
                  <span className={scoreColor(s.score)}>{Math.round(s.score)}%</span>
                </li>
              ))}
              {a.weak_students.length === 0 && (
                <li className="py-2 text-slate-500">No readiness data yet.</li>
              )}
            </ul>
          </CardBody>
        </Card>

        <Card>
          <CardHeader title="Weakest topics" description="Class average." />
          <CardBody className="pt-0">
            <ul className="divide-y divide-slate-100 text-sm">
              {a.weak_topics.map((t) => (
                <li key={t.topic_code} className="flex items-center justify-between gap-3 py-2">
                  <span className="min-w-0 truncate text-slate-700">
                    {t.topic_code} {t.topic_title}
                  </span>
                  <span className={scoreColor(t.avg_score)}>{Math.round(t.avg_score)}%</span>
                </li>
              ))}
              {a.weak_topics.length === 0 && (
                <li className="py-2 text-slate-500">No readiness data yet.</li>
              )}
            </ul>
          </CardBody>
        </Card>
      </div>
    </div>
  );
}
