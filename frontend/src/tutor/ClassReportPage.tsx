import type { ReactNode } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Printer } from "lucide-react";
import {
  classReport,
  type AttendanceReport,
  type ChapterReport,
  type ClassReport,
  type MistakePatterns,
  type PlanReport,
} from "../api/classReport";
import { Button, buttonClasses } from "../components/controls";
import { ErrorState, NotFoundState, PageHeader, PageSkeleton } from "../components/page";
import ReadinessFigure from "../components/ReadinessFigure";
import { EmptyState, SectionCard, SectionHeader } from "../components/ui";
import { ApiError } from "../api/client";
import { ABSENT } from "../lib/labels";
import { shortDay } from "../lib/planDates";
import { bandOf } from "../lib/readiness";

const pct = (rate: number) => `${Math.round(rate * 100)}%`;
const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;
const absent = (text: string = ABSENT.noEvidence) => <span className="text-ink-500">{text}</span>;

function Section({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children: ReactNode;
}) {
  // break-inside-avoid keeps a section whole on the printed page.
  return (
    <SectionCard className="space-y-4 print:break-inside-avoid print:shadow-none">
      <SectionHeader title={title} description={description} />
      {children}
    </SectionCard>
  );
}

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <dt className="text-xs text-ink-500">{label}</dt>
      <dd className="mt-0.5 text-[15px] text-ink-900">{children}</dd>
    </div>
  );
}

function countdown(plan: PlanReport): ReactNode {
  if (plan.days_to_exam == null || !plan.exam_date) return absent();
  const days = plan.days_to_exam;
  if (days < 0) return `The exam date has passed (${shortDay(plan.exam_date)})`;
  if (days === 0) return "The exam is today";
  const weeks = Math.round(days / 7);
  return (
    <>
      {plural(days, "day")}
      {days >= 14 && <span className="text-ink-500"> (about {plural(weeks, "week")})</span>} ·{" "}
      {shortDay(plan.exam_date)}
    </>
  );
}

function positionLine(plan: PlanReport): ReactNode {
  if (plan.position == null || plan.behind_by == null || plan.lessons_due == null) {
    return "The plan hasn't reached its first lesson yet";
  }
  if (plan.position === "behind") {
    return `Behind by ${plural(plan.behind_by, "lesson")}`;
  }
  if (plan.position === "ahead") {
    return `Ahead by ${plural(plan.ahead_by ?? 0, "lesson")}`;
  }
  return "On schedule";
}

function PlanSection({ plan, groupId }: { plan: PlanReport; groupId: number }) {
  if (!plan.has_plan) {
    return (
      <Section title="Plan & countdown">
        <EmptyState
          title="No teaching plan accepted yet"
          hint="This report is built around the plan. Accept one and it shows where the class stands, how many lessons are left and how long until the exam."
          action={
            <Link to={`/tutor/groups/${groupId}`} className={buttonClasses("secondary", "sm")}>
              Open the class
            </Link>
          }
        />
      </Section>
    );
  }
  return (
    <Section
      title="Plan & countdown"
      description="Counted from the class's accepted teaching plan and the lessons recorded against it."
    >
      <dl className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Fact label="Exam countdown">{countdown(plan)}</Fact>
        <Fact label="Against the plan">
          {positionLine(plan)}
          {plan.lessons_due != null && plan.behind_by != null && (
            <span className="block text-xs text-ink-500">
              {plan.lessons_due - plan.behind_by} of {plural(plan.lessons_due, "lesson")} dated
              before today recorded
            </span>
          )}
        </Fact>
        <Fact label="Lessons taught">
          {plan.lessons_taught} of {plan.lessons_planned}
          <span className="block text-xs text-ink-500">{plan.lessons_left} left in the plan</span>
        </Fact>
        <Fact label="Up next">
          {plan.up_next ? (
            <>
              {plan.up_next.chapter_code} {plan.up_next.chapter_title}
              <span className="block text-xs text-ink-500">
                {shortDay(plan.up_next.scheduled_date)}
                {plan.up_next.topics.length > 0 && ` · ${plan.up_next.topics.join(", ")}`}
              </span>
            </>
          ) : (
            <span className="text-ink-500">Every planned lesson has been started</span>
          )}
        </Fact>
      </dl>
    </Section>
  );
}

const STATE_LABEL: Record<ChapterReport["state"], string> = {
  not_started: "Not yet taught",
  in_progress: "In progress",
  taught: "Taught",
};

function ChapterCard({ chapter }: { chapter: ChapterReport }) {
  return (
    <div className="rounded-lg border border-line p-4 print:break-inside-avoid">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h4 className="font-display text-base text-ink-900">
          {chapter.code} {chapter.title}
        </h4>
        <p className="text-xs text-ink-500">
          {STATE_LABEL[chapter.state]} · {chapter.topics_taught} of{" "}
          {plural(chapter.topics_total, "topic")} taught
          {chapter.lessons_planned != null &&
            ` · ${chapter.lessons_taught} of ${plural(chapter.lessons_planned, "planned lesson")}`}
        </p>
      </div>
      {chapter.topics.length > 0 && (
        <table className="mt-3 w-full text-left text-sm">
          <thead className="text-xs text-ink-500">
            <tr>
              <th className="py-1 pr-2 font-medium">Topic</th>
              <th className="py-1 pr-2 font-medium">Taught</th>
              <th className="py-1 font-medium">Class mastery</th>
            </tr>
          </thead>
          <tbody>
            {chapter.topics.map((t) => (
              <tr key={t.topic_id} className="border-t border-line">
                <td className="py-1.5 pr-2 text-ink-900">
                  {t.code} {t.title}
                </td>
                <td className="py-1.5 pr-2 text-ink-700">{t.taught ? "Yes" : "Not yet"}</td>
                <td className="py-1.5 text-ink-700">
                  {t.avg_score == null ? (
                    absent()
                  ) : (
                    <>
                      <span className="tabular-nums">{Math.round(t.avg_score)}%</span>
                      <span className="text-ink-500">
                        {" "}
                        · {plural(t.student_count ?? 0, "learner")}
                        {t.includes_tutor_estimate && " · includes a tutor estimate"}
                      </span>
                      {t.weak && <span className="ml-2 font-medium text-risk-600">Weak</span>}
                    </>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function ChaptersSection({ report }: { report: ClassReport }) {
  const measured = report.chapters.some((c) => c.topics.some((t) => t.avg_score != null));
  return (
    <Section
      title="Chapters & topics"
      description="What has been taught, from the lessons recorded; mastery is the class average of confident evidence."
    >
      <p className="text-sm text-ink-700">
        {report.weak_topics.length > 0 ? (
          <>
            <span className="font-medium">Weak topics</span> (class average at or below{" "}
            {Math.round(report.weak_threshold)}%):{" "}
            {report.weak_topics
              .map((t) => `${t.topic_title} (${Math.round(t.avg_score)}%)`)
              .join(", ")}
          </>
        ) : measured ? (
          `No topic is at or below the weak threshold of ${Math.round(report.weak_threshold)}%.`
        ) : (
          <>Weak topics: {absent()}</>
        )}
      </p>
      {report.chapters.length === 0 ? (
        <EmptyState title="This subject has no chapters yet" />
      ) : (
        <div className="space-y-3">
          {report.chapters.map((c) => (
            <ChapterCard key={c.chapter_id} chapter={c} />
          ))}
        </div>
      )}
    </Section>
  );
}

function MistakesSection({ mistakes }: { mistakes: MistakePatterns }) {
  return (
    <Section
      title="Mistake patterns"
      description={`Tagged mistakes in marked work analysed since ${shortDay(mistakes.since)}.`}
    >
      {mistakes.total_mistakes == null ? (
        <p className="text-sm">
          {absent()}
          <span className="text-ink-500"> — no marked work has been analysed in this period.</span>
        </p>
      ) : mistakes.categories.length === 0 ? (
        <p className="text-sm text-ink-700">
          No mistakes were tagged across {plural(mistakes.analysed_questions, "analysed question")}.
        </p>
      ) : (
        <>
          <p className="text-sm text-ink-500">
            {plural(mistakes.total_mistakes, "mistake")} across{" "}
            {plural(mistakes.analysed_questions, "analysed question")},{" "}
            {plural(mistakes.students_affected ?? 0, "learner")} affected.
          </p>
          <table className="w-full text-left text-sm">
            <thead className="text-xs text-ink-500">
              <tr>
                <th className="py-1 pr-2 font-medium">Category</th>
                <th className="py-1 pr-2 font-medium">Mistakes</th>
                <th className="py-1 pr-2 font-medium">Share</th>
                <th className="py-1 font-medium">Learners</th>
              </tr>
            </thead>
            <tbody>
              {mistakes.categories.map((c) => (
                <tr key={c.category_id} className="border-t border-line">
                  <td className="py-1.5 pr-2 text-ink-900">{c.category_name}</td>
                  <td className="py-1.5 pr-2 tabular-nums text-ink-700">{c.mistakes}</td>
                  <td className="py-1.5 pr-2 tabular-nums text-ink-700">{pct(c.share)}</td>
                  <td className="py-1.5 tabular-nums text-ink-700">{c.students_affected}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </Section>
  );
}

function AttendanceSection({ attendance }: { attendance: AttendanceReport }) {
  const marked = attendance.present + attendance.absent;
  return (
    <Section
      title="Attendance"
      description="From the lesson register. A lesson nobody marked is not taken, never absent."
    >
      {attendance.learners.length === 0 ? (
        <EmptyState title="No learners are enrolled yet" />
      ) : (
        <>
          <p className="text-sm text-ink-700">
            {attendance.rate == null ? (
              <>Class attendance: {absent()}</>
            ) : (
              <>
                Class attendance{" "}
                <span className="font-medium tabular-nums">{pct(attendance.rate)}</span> present
                <span className="text-ink-500">
                  {" "}
                  ({attendance.present} of {plural(marked, "mark")})
                </span>
              </>
            )}
            {attendance.not_taken > 0 && (
              <span className="text-ink-500"> · {attendance.not_taken} not taken</span>
            )}
          </p>
          <table className="w-full text-left text-sm">
            <thead className="text-xs text-ink-500">
              <tr>
                <th className="py-1 pr-2 font-medium">Learner</th>
                <th className="py-1 pr-2 font-medium">Present</th>
                <th className="py-1 pr-2 font-medium">Absent</th>
                <th className="py-1 pr-2 font-medium">Not taken</th>
                <th className="py-1 font-medium">Rate</th>
              </tr>
            </thead>
            <tbody>
              {attendance.learners.map((l) => (
                <tr key={l.student_id} className="border-t border-line">
                  <td className="py-1.5 pr-2 text-ink-900">{l.student_name}</td>
                  <td className="py-1.5 pr-2 tabular-nums text-ink-700">{l.present}</td>
                  <td className="py-1.5 pr-2 tabular-nums text-ink-700">{l.absent}</td>
                  <td className="py-1.5 pr-2 tabular-nums text-ink-700">{l.not_taken}</td>
                  <td className="py-1.5 tabular-nums text-ink-700">
                    {l.rate == null ? absent("not marked yet") : pct(l.rate)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </Section>
  );
}

/**
 * One class's report, led by the teaching plan (owner, 2026-10-05: everything
 * revolves around it), then the syllabus read against it, then mistakes and
 * attendance. Everything arrives assembled from one endpoint, so the page
 * computes nothing: a figure it cannot show is absent, never 0 (PROD-2).
 */
export default function ClassReportPage() {
  const groupId = Number(useParams().groupId);
  const report = useQuery({
    queryKey: ["class-report", groupId],
    queryFn: () => classReport(groupId),
    enabled: Number.isFinite(groupId),
  });
  const back = { to: "/tutor/reports", label: "All reports" };

  if (report.isLoading) return <PageSkeleton rows={4} label="Loading the report" />;
  if (report.isError) {
    return report.error instanceof ApiError && report.error.status === 404 ? (
      <NotFoundState title="We couldn't find that class" back={back} />
    ) : (
      <ErrorState
        title="The report didn't load"
        error={report.error}
        onRetry={() => report.refetch()}
      />
    );
  }
  const data = report.data;
  if (!data) return null;
  const r = data.readiness;

  return (
    <div>
      <PageHeader
        back={back}
        title={`${data.name} report`}
        documentTitle={`${data.name} report`}
        description={`${data.subject_name} · generated ${new Date(data.generated_at).toLocaleDateString()}`}
        actions={
          <Button
            variant="secondary"
            size="md"
            className="print:hidden"
            onClick={() => window.print()}
          >
            <Printer aria-hidden className="mr-2 h-4 w-4" />
            Print
          </Button>
        }
      />
      <div className="space-y-6">
        <PlanSection plan={data.plan} groupId={data.group_id} />
        <Section title="Class readiness">
          <div className="text-sm">
            <ReadinessFigure
              score={r.score ?? null}
              grade={r.predicted_grade ?? null}
              status={bandOf(r.status)}
              boundariesMissing={r.boundaries_missing}
            />
            <p className="mt-1 text-xs text-ink-500">
              Based on {r.students_with_evidence} of {plural(r.member_count, "learner")} with
              evidence.
            </p>
          </div>
        </Section>
        <ChaptersSection report={data} />
        <MistakesSection mistakes={data.mistakes} />
        <AttendanceSection attendance={data.attendance} />
      </div>
    </div>
  );
}
