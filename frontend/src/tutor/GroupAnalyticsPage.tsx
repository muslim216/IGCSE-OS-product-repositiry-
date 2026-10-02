import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { groupAnalytics } from "../api/readiness";
import { SectionCard } from "../components/ui";
import { ErrorState, SectionSkeleton } from "../components/page";

function CardTitle({ title, description }: { title: string; description: string }) {
  return (
    <div>
      <h2 className="text-lg text-ink-900">{title}</h2>
      <p className="mt-0.5 text-sm text-ink-500">{description}</p>
    </div>
  );
}

/*
 * Scores here are shown in plain ink rather than coloured green/amber/red.
 * This feed carries a bare percentage and no band, and colouring it by a
 * literal 70/50 cut would claim a threshold the subject never set (UX-28) —
 * the class overview above carries the real, boundary-derived status.
 */
export default function GroupAnalyticsPage() {
  const { groupId } = useParams();
  const id = Number(groupId);
  const analytics = useQuery({
    queryKey: ["analytics", id],
    queryFn: () => groupAnalytics(id),
  });

  if (analytics.isLoading) return <SectionSkeleton rows={5} label="Loading analytics" />;
  if (analytics.isError || !analytics.data) {
    return (
      <ErrorState
        title="Class analytics didn't load"
        error={analytics.error}
        onRetry={() => analytics.refetch()}
      />
    );
  }
  const a = analytics.data;
  const hasReadiness = a.weak_students.length > 0;

  // Rendered as a tab inside GroupLayout, which already shows the class header.
  return (
    <div className="space-y-6">
      <SectionCard>
        <CardTitle
          title="AI marking agreement"
          description="How often your final mark matched the AI's first mark, on questions you reviewed yourself."
        />
        {a.agreement.agreement_rate !== null ? (
          <p className="mt-4 flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <span className="font-display text-3xl text-ink-900">
              {a.agreement.agreement_rate}%
            </span>
            <span className="text-sm text-ink-500">
              {a.agreement.ai_agreed} of {a.agreement.total_marked_questions}{" "}
              {a.agreement.total_marked_questions === 1 ? "question" : "questions"} matched
            </span>
          </p>
        ) : (
          <p className="mt-4 text-sm text-ink-500">
            Not enough data yet — this appears once you've finalized a question the AI marked.
          </p>
        )}
      </SectionCard>

      <div className="grid gap-6 md:grid-cols-2">
        <SectionCard>
          <CardTitle
            title="Readiness by student"
            description="Lowest first, for students with a readiness score."
          />
          {hasReadiness ? (
            <ul className="mt-3 divide-y divide-line text-sm">
              {a.weak_students.map((s) => (
                <li key={s.student_id} className="flex items-center justify-between gap-3 py-2">
                  <Link
                    to={`/tutor/students/${s.student_id}?group=${id}`}
                    className="font-medium text-ink-900 hover:text-brand-600"
                  >
                    {s.student_name}
                  </Link>
                  <span className="tabular-nums text-ink-700">
                    {Math.round(s.score)}%<span className="sr-only"> readiness</span>
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-3 text-sm text-ink-500">
              No student has a readiness score yet. Scores appear once their work is marked.
            </p>
          )}
        </SectionCard>

        <SectionCard>
          <CardTitle
            title="Weakest topics"
            description="Class average on each topic, lowest first."
          />
          {a.weak_topics.length > 0 ? (
            <ul className="mt-3 divide-y divide-line text-sm">
              {a.weak_topics.map((t) => (
                <li key={t.topic_code} className="flex items-center justify-between gap-3 py-2">
                  <span className="min-w-0 text-ink-700">
                    {t.topic_title}
                    <span className="ml-2 text-xs text-ink-500">{t.topic_code}</span>
                    {t.includes_tutor_estimate && (
                      <span className="ml-2 text-xs text-ink-500">includes tutor estimate</span>
                    )}
                  </span>
                  <span className="shrink-0 text-right tabular-nums">
                    <span className="text-ink-700">{Math.round(t.avg_score)}%</span>
                    <span className="ml-2 text-xs text-ink-500">
                      {t.student_count} {t.student_count === 1 ? "student" : "students"}
                    </span>
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            /* Not "no readiness data": a class can have every learner scored
               and still list no topic here. A topic is listed only when its
               class average — from confident, topic-tagged marked work — is at
               or below the weak-topic threshold. So an empty list is either
               "no topic has enough such work yet" or "none is at or below the
               threshold", and the API does not say which: the copy claims
               neither, and the line under it names both conditions. */
            <div className="mt-3 text-sm text-ink-500">
              {hasReadiness ? (
                <>
                  <p>No weak topics to show yet.</p>
                  <p className="mt-1">
                    A topic shows here once there's enough marked work tagged to it and the class
                    average is at or below your{" "}
                    <Link
                      to="/tutor/preferences"
                      className="font-medium text-brand-600 hover:text-brand-700"
                    >
                      weak-topic threshold
                    </Link>
                    .
                  </p>
                </>
              ) : (
                <p>Topic averages appear once marked work is tagged to syllabus topics.</p>
              )}
            </div>
          )}
        </SectionCard>
      </div>
    </div>
  );
}
