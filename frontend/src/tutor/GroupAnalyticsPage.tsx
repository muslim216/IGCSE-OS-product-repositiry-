import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { groupAnalytics } from "../api/readiness";
import { classOverview } from "../api/today";
import { Button } from "../components/controls";
import ReadinessFigure from "../components/ReadinessFigure";
import { ABSENT } from "../lib/labels";
import { bandOf } from "../lib/readiness";
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
 * Topic scores here are shown in plain ink rather than coloured green/amber/red.
 * That feed carries a bare percentage and no band, and colouring it by a
 * literal 70/50 cut would claim a threshold the subject never set (UX-28).
 * "Readiness by student" is read from the class overview instead, which bands
 * each learner from the subject's own boundaries, so it can say grade, status
 * and percentage like every other readiness figure (coherence C.6).
 */
export default function GroupAnalyticsPage() {
  const { groupId } = useParams();
  const id = Number(groupId);
  const analytics = useQuery({
    queryKey: ["analytics", id],
    queryFn: () => groupAnalytics(id),
  });

  // Same key as the class header's query, so on the landing tab this is a cache
  // hit rather than a second request.
  const overview = useQuery({
    queryKey: ["class-overview", id],
    queryFn: () => classOverview(id),
  });
  // Lowest first, as the card promises; a learner with no score is absent.
  const scored = (overview.data?.learners ?? [])
    .filter((l) => l.score !== null)
    .sort((x, y) => (x.score as number) - (y.score as number));

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
  // Either source saying a learner is scored is enough: the student card reads
  // the class overview, the topic card's wording reads the analytics feed, and
  // neither should claim "no scores" while the other has some.
  const hasReadiness = a.weak_students.length > 0 || scored.length > 0;

  // Rendered as a tab inside GroupLayout, which already shows the class header.
  return (
    <div className="space-y-6">
      <SectionCard>
        <CardTitle
          title="How often you agreed with the AI"
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
          {overview.isPending ? (
            <SectionSkeleton rows={3} label="Loading readiness by student" />
          ) : overview.isError ? (
            <div className="mt-3 flex flex-wrap items-center gap-3">
              <p role="alert" className="text-sm text-ink-500">
                {ABSENT.loadFailedRetry}
              </p>
              <Button variant="secondary" size="sm" onClick={() => overview.refetch()}>
                Try again
              </Button>
            </div>
          ) : scored.length > 0 ? (
            <ul className="mt-3 divide-y divide-line text-sm">
              {scored.map((s) => (
                <li
                  key={s.student_id}
                  className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 py-2"
                >
                  <Link
                    to={`/tutor/students/${s.student_id}?group=${id}`}
                    className="font-medium text-ink-900 hover:text-brand-600"
                  >
                    {s.student_name}
                  </Link>
                  <ReadinessFigure
                    score={s.score}
                    grade={s.predicted_grade}
                    status={bandOf(s.verdict.status)}
                    boundariesMissing={overview.data?.boundaries_missing ?? false}
                  />
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
            /* The list holds only topics at or below the tutor's weak
               threshold — a 0–100 score, 60 unless the tutor changed it
               (task 5.6) — filtered from the class means, which count
               medium/high-confidence marks only. So empty has three meanings,
               and each claim must be one the data supports (PROD-2): means
               exist and none is weak; learners are scored but no topic has a
               mean, so nothing was compared; or there is nothing at all.
               `topic_mean_count` is what tells the first two apart. */
            <div className="mt-3 text-sm text-ink-500">
              {a.topic_mean_count > 0 ? (
                <>
                  <p>No topic is at or below the weak threshold.</p>
                  <p className="mt-1">
                    You set the threshold in{" "}
                    <Link
                      to="/tutor/settings#preferences"
                      className="font-medium text-brand-600 hover:text-brand-700"
                    >
                      Preferences
                    </Link>
                    .
                  </p>
                </>
              ) : hasReadiness ? (
                <>
                  <p>Not enough confident topic data yet.</p>
                  <p className="mt-1">
                    A topic's class average appears once marked work is tagged to it.
                  </p>
                </>
              ) : (
                <p>No readiness data yet.</p>
              )}
            </div>
          )}
          {/* A student's own weak topics also count low-confidence marks, so
              the two lists can differ. */}
          {a.weak_topics.length > 0 && (
            <p className="mt-2 text-xs text-ink-500">
              Class averages count medium- and high-confidence marks only.
            </p>
          )}
        </SectionCard>
      </div>
    </div>
  );
}
