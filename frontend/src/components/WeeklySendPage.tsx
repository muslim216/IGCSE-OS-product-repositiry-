import type { ReactNode } from "react";
import { Link, Navigate, useLocation, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useAuth } from "../auth/AuthContext";
import { ApiError } from "../api/client";
import {
  myWeeklySends,
  weeklySend,
  type AttendanceFacts,
  type HomeworkFacts,
  type ParentClassFacts,
  type PlanFacts,
  type StudentClassFacts,
  type TutorClassFacts,
  type WeeklySend,
} from "../api/weeklySend";
import { ABSENT } from "../lib/labels";
import { bandOf } from "../lib/readiness";
import { plural, shellFor, weekLabel, weeklySendPath, type ShellHome } from "../lib/weeklySend";
import { ErrorState, NotFoundState, PageHeader, PageSkeleton } from "./page";
import ReadinessFigure from "./ReadinessFigure";
import { SectionCard, StatusBadge, type ReadinessStatus } from "./ui";

/**
 * One stored weekly send (tasks 8.2, 8.4), for whichever of the three readers
 * it was written to.
 *
 * Everything here is "as at the end of that week": the page renders the stored
 * facts and never recomputes one, so a report opened on Thursday says what it
 * said on Sunday. An absent measurement is said in words — never 0, 0% or an
 * empty bar (PROD-2).
 *
 * The tutor's send leads each class with its place in the teaching plan; the
 * parent's has no topic breakdown and no mistakes (AV-64), and that is decided
 * by what the server stored, not by what this page chooses to hide.
 */

const DIRECTION_WORDS = {
  up: "Readiness up since last week",
  down: "Readiness down since last week",
  flat: "Readiness steady since last week",
} as const;

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 py-2.5 text-sm">
      <dt className="text-ink-500">{label}</dt>
      <dd className="text-right text-ink-900">{children}</dd>
    </div>
  );
}

function ClassCard({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: string | null;
  children: ReactNode;
}) {
  return (
    <SectionCard>
      <h2 className="font-display text-lg text-ink-900">{title}</h2>
      {subtitle && <p className="text-sm text-ink-500">{subtitle}</p>}
      <dl className="mt-3 divide-y divide-line">{children}</dl>
    </SectionCard>
  );
}

function attendanceText(a: AttendanceFacts | null | undefined): string {
  if (!a) return "No lessons this week";
  const marked = a.present + a.absent;
  if (marked === 0) return `${plural(a.lessons_held, "lesson")}, register not taken`;
  const untaken = a.not_taken > 0 ? ` · ${a.not_taken} not taken` : "";
  return `${a.present} present · ${a.absent} absent${untaken}`;
}

function homeworkText(h: HomeworkFacts | null | undefined): string {
  if (!h) return "None set or due this week";
  const parts = [`${h.set_count} set`, `${h.handed_in_count} handed in`];
  if (h.missing_count > 0) parts.push(`${h.missing_count} missing`);
  return parts.join(" · ");
}

function chapterName(c: { code: string; title: string } | null | undefined): string | null {
  if (!c) return null;
  return c.code ? `${c.code} ${c.title}` : c.title;
}

function planPosition(plan: PlanFacts): string {
  if (plan.lessons_behind == null) return "Not started yet";
  if (plan.lessons_behind > 0) return `${plural(plan.lessons_behind, "lesson")} behind`;
  if (plan.lessons_ahead > 0) return `${plural(plan.lessons_ahead, "lesson")} ahead`;
  return "On schedule";
}

function PlanRows({ plan }: { plan: PlanFacts | null | undefined }) {
  if (!plan) {
    return <Row label="Teaching plan">No accepted plan for this class</Row>;
  }
  const next = chapterName(plan.next_chapter);
  return (
    <>
      <Row label="This week in the plan">
        {chapterName(plan.this_week_chapter) ?? "Nothing planned this week"}
      </Row>
      <Row label="Lessons taught">
        {plan.lessons_planned_this_week > 0
          ? `${plan.lessons_taught_this_week} of ${plan.lessons_planned_this_week} planned`
          : "None planned this week"}
      </Row>
      <Row label="Against the plan">{planPosition(plan)}</Row>
      {next && (
        <Row label="Next">
          {next}
          {plan.next_chapter_homework_set === false && (
            <span className="block text-xs text-ink-500">No homework set for it yet</span>
          )}
        </Row>
      )}
      {plan.weeks_to_exam != null && (
        <Row label="Exam">{plural(plan.weeks_to_exam, "week")} away</Row>
      )}
    </>
  );
}

function TutorClass({ c }: { c: TutorClassFacts }) {
  const measured = c.verdicts.filter((v) => v.status !== "not_enough_data");
  return (
    <ClassCard title={c.group_name} subtitle={c.subject_name}>
      <PlanRows plan={c.plan} />
      <Row label="Learners">
        {measured.length > 0 ? (
          <span className="flex flex-wrap justify-end gap-x-3 gap-y-1">
            {measured.map((v) => (
              <span key={v.status} className="flex items-center gap-1.5">
                <span className="tabular-nums">{v.learners}</span>
                <StatusBadge status={v.status as ReadinessStatus} />
              </span>
            ))}
          </span>
        ) : (
          <span className="text-ink-500">{ABSENT.noEvidence}</span>
        )}
      </Row>
      {c.readiness_direction && (
        <Row label="Direction">{DIRECTION_WORDS[c.readiness_direction]}</Row>
      )}
      {c.weak_topics.length > 0 && (
        <Row label="Weak topics">
          {c.weak_topics.map((t) => `${t.title} (${t.learners})`).join(" · ")}
        </Row>
      )}
      <Row label="Attendance">{attendanceText(c.attendance)}</Row>
      <Row label="Homework">{homeworkText(c.homework)}</Row>
      {c.punctuality && (
        <Row label="Handed in on time">
          {c.punctuality.on_time} on time · {c.punctuality.late} late
        </Row>
      )}
    </ClassCard>
  );
}

function StudentClass({ c }: { c: StudentClassFacts }) {
  const next = chapterName(c.next_chapter);
  return (
    <ClassCard
      title={c.subject_name ?? c.group_name}
      subtitle={c.subject_name ? c.group_name : null}
    >
      <Row label="Where you stand">
        {/* No status colour for the learner: a kind word is not set in a warning tone. */}
        <ReadinessFigure score={c.readiness_score} grade={c.predicted_grade} />
      </Row>
      {c.weak_topics.length > 0 && <Row label="Focus on">{c.weak_topics.join(" · ")}</Row>}
      {chapterName(c.this_week_chapter) && (
        <Row label="This week">{chapterName(c.this_week_chapter)}</Row>
      )}
      {next && <Row label="Next">{next}</Row>}
      <Row label="Lessons">{attendanceText(c.attendance)}</Row>
      <Row label="Homework">{homeworkText(c.homework)}</Row>
    </ClassCard>
  );
}

function ParentClass({ c }: { c: ParentClassFacts }) {
  return (
    <ClassCard
      title={c.subject_name ?? c.group_name}
      subtitle={c.subject_name ? c.group_name : null}
    >
      <Row label="Readiness">
        <ReadinessFigure
          score={c.readiness_score}
          grade={c.predicted_grade}
          status={bandOf(c.verdict)}
        />
      </Row>
      {c.readiness_direction && (
        <Row label="Direction">{DIRECTION_WORDS[c.readiness_direction]}</Row>
      )}
      {chapterName(c.chapter) && <Row label="Studying now">{chapterName(c.chapter)}</Row>}
      <Row label="Attendance">{attendanceText(c.attendance)}</Row>
      <Row label="Homework">{homeworkText(c.homework)}</Row>
    </ClassCard>
  );
}

function Paragraphs({ send }: { send: WeeklySend }) {
  if (send.paragraphs.length === 0) return null;
  return (
    <SectionCard>
      <h2 className="avora-label mb-2">In a few words</h2>
      <div className="space-y-3">
        {send.paragraphs.map((p) => (
          <p key={p.about} className="text-sm leading-relaxed text-ink-700">
            {send.paragraphs.length > 1 && (
              <span className="font-medium text-ink-900">{p.about}: </span>
            )}
            {p.text}
          </p>
        ))}
      </div>
    </SectionCard>
  );
}

function Body({ send }: { send: WeeklySend }) {
  if (send.tutor) {
    const t = send.tutor;
    return (
      <>
        <SectionCard>
          <dl className="divide-y divide-line">
            <Row label="Marked this week">
              {t.marked
                ? `${plural(t.marked.marked, "piece")} · ${t.marked.auto_finalized} without you`
                : "Nothing marked this week"}
            </Row>
            <Row label="Waiting for you">
              {t.review_queue > 0 ? (
                <Link to="/tutor/review" className="font-medium text-brand-600">
                  {plural(t.review_queue, "submission")}
                </Link>
              ) : (
                "Nothing"
              )}
            </Row>
          </dl>
        </SectionCard>
        <Paragraphs send={send} />
        {t.classes.map((c) => (
          <TutorClass key={c.group_id} c={c} />
        ))}
      </>
    );
  }
  if (send.student) {
    const s = send.student;
    return (
      <>
        {s.marked && (
          <SectionCard>
            <p className="text-sm text-ink-700">
              {plural(s.marked.marked, "piece")} of your work marked this week.
            </p>
          </SectionCard>
        )}
        {s.classes.map((c) => (
          <StudentClass key={c.group_id} c={c} />
        ))}
      </>
    );
  }
  if (send.parent) {
    const several = send.parent.children.length > 1;
    return (
      <>
        <Paragraphs send={send} />
        {send.parent.children.map((child) => (
          <div key={child.child_name} className="space-y-4">
            {several && <h2 className="font-display text-xl text-ink-900">{child.child_name}</h2>}
            {child.classes.length === 0 ? (
              <SectionCard>
                <p className="text-sm text-ink-500">
                  {child.child_name} isn&apos;t in a class yet, so there is nothing to report.
                </p>
              </SectionCard>
            ) : (
              child.classes.map((c) => <ParentClass key={c.group_name} c={c} />)
            )}
          </div>
        ))}
      </>
    );
  }
  return null;
}

function title(send: WeeklySend): string {
  if (send.parent && send.parent.children.length === 1) {
    return `${send.parent.children[0].child_name}'s week`;
  }
  return send.tutor ? "Your classes this week" : "Your week";
}

function Earlier({ currentId, home }: { currentId: number; home: ShellHome }) {
  const sends = useQuery({ queryKey: ["weekly-send", "mine"], queryFn: myWeeklySends });
  const others = (sends.data ?? []).filter((s) => s.id !== currentId);
  if (others.length === 0) return null;
  return (
    <details className="text-sm print:hidden">
      <summary className="cursor-pointer text-ink-500">Earlier weeks</summary>
      <ul className="mt-2 space-y-1">
        {others.map((s) => (
          <li key={s.id}>
            <Link to={weeklySendPath(home, s.id)} className="text-brand-600">
              {weekLabel(s.week_start, s.week_end)}
            </Link>
          </li>
        ))}
      </ul>
    </details>
  );
}

export default function WeeklySendPage() {
  // The shell this page is mounted in ("/tutor/weekly/7" -> "/tutor"). Read from
  // the address rather than the send's audience: a tutor reading what went to a
  // learner stays in the tutor's shell.
  const home = shellFor(useLocation().pathname.split("/")[1] ?? "");
  const sendId = Number(useParams().sendId);
  const valid = Number.isInteger(sendId) && sendId > 0;
  const send = useQuery({
    queryKey: ["weekly-send", sendId],
    queryFn: () => weeklySend(sendId),
    enabled: valid,
  });
  const missing = !valid || (send.error instanceof ApiError && send.error.status === 404);

  if (missing) {
    return (
      <NotFoundState
        title="That weekly send isn't here"
        body="It may belong to a different account, or the link may be mistyped."
        back={{ to: home, label: "Back to home" }}
      />
    );
  }
  if (send.isLoading) return <PageSkeleton rows={4} label="Loading the weekly send" />;
  if (send.isError || !send.data) {
    return (
      <ErrorState
        title="The weekly send didn't load"
        error={send.error}
        onRetry={() => void send.refetch()}
      />
    );
  }
  return (
    <div className="max-w-3xl space-y-4">
      <PageHeader
        eyebrow={`Week of ${weekLabel(send.data.week_start, send.data.week_end)}`}
        title={title(send.data)}
        description="As it stood when the week closed."
        back={{ to: home, label: "Home" }}
      />
      <Body send={send.data} />
      <Earlier currentId={send.data.id} home={home} />
    </div>
  );
}

/** `/weekly/:sendId` — the address a WhatsApp or email message carries. It
 *  cannot know the reader's role, so it sends them to the same send inside
 *  their own shell. */
export function WeeklySendRedirect() {
  const { user } = useAuth();
  const { sendId } = useParams();
  if (!user) return <Navigate to="/login" replace />;
  return <Navigate to={weeklySendPath(shellFor(user.role), Number(sendId))} replace />;
}
