import { useState } from "react";
import { Link } from "react-router-dom";
import { BookOpen, CalendarPlus, ChevronRight, Ruler, Users } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { todayView, type ClassStripRow } from "../../api/today";
import { listGroups } from "../../api/groups";
import { assignmentsNeedingAttention } from "../../api/homework";
import { StatusBadge, useToast } from "../../components/ui";
import { Button, buttonClasses } from "../../components/controls";
import { ErrorState, PageHeader, PageSkeleton } from "../../components/page";
import { ABSENT, REASON_LABELS } from "../../lib/labels";
import { coverageLabel, isClearDay, verdictLine1, verdictLine2 } from "../../lib/verdict";
import ClassNarrative from "./ClassNarrative";
import CreateLessonModal from "./CreateLessonModal";

/**
 * The tutor's home, rebuilt: verdict → class strip → TODAY → WHAT CHANGED →
 * NEEDS YOU.
 *
 * The rule that shapes every branch below: a section with nothing to report is
 * NOT RENDERED (UX-29). It never becomes an empty card, a spinner where the
 * previous value would do, or a `0` standing in for a missing measurement
 * (PROD-2, UX-19). A completely clear day ends with a sentence, not a screen of
 * empty panels.
 */

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h2 className="avora-label mb-3">{title}</h2>
      {children}
    </section>
  );
}

function ClassRow({ row }: { row: ClassStripRow }) {
  const coverage = coverageLabel(row);
  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-1.5 border-t border-line py-3.5">
      <Link
        to={`/tutor/groups/${row.group_id}/students`}
        className="font-medium text-ink-900 hover:text-brand-600"
      >
        {row.name}
      </Link>
      <span className="text-sm text-ink-500">{row.subject_name}</span>

      {row.status ? (
        <>
          {/* Labelled: a bare "5" beside a class name did not say it was the
              class's predicted grade. */}
          <span className="text-sm text-ink-700">
            Predicted grade{" "}
            <span className="font-display text-[15px] tabular-nums text-ink-900">
              {row.predicted_grade}
            </span>
          </span>
          <StatusBadge status={row.status} />
        </>
      ) : row.boundaries_missing ? (
        <span className="text-sm text-ink-500">
          {ABSENT.noBoundaries}{" "}
          <Link to="/tutor/boundaries" className="font-medium text-brand-600 hover:text-brand-700">
            {ABSENT.noBoundariesAction}
          </Link>
        </span>
      ) : (
        <span className="text-sm text-ink-500">{ABSENT.noEvidence}</span>
      )}

      {coverage && (
        <span
          className="ml-auto text-xs tabular-nums text-ink-500"
          title="Learners with a readiness score"
        >
          {coverage} with a score
        </span>
      )}
    </li>
  );
}

export default function TodayDashboard() {
  const [createOpen, setCreateOpen] = useState(false);
  const { toast, showToast } = useToast();

  const today = useQuery({ queryKey: ["today"], queryFn: todayView });
  const attention = useQuery({
    queryKey: ["assignments-attention"],
    queryFn: assignmentsNeedingAttention,
  });
  // Only the lesson modal needs full Group objects; the surface itself renders
  // from the aggregate, so this never gates what the tutor reads.
  const groups = useQuery({ queryKey: ["groups"], queryFn: listGroups });

  if (today.isLoading) return <PageSkeleton rows={3} label="Loading today" />;

  if (today.isError || !today.data) {
    return (
      <ErrorState
        title="Today couldn't be loaded"
        error={today.error}
        onRetry={() => today.refetch()}
      />
    );
  }

  const view = today.data;
  const line1 = verdictLine1(view);
  const line2 = verdictLine2(view);
  const attentionItems = (attention.data ?? []).slice(0, 5);
  // The aggregate's review_count and the attention list are different measures
  // from different endpoints — attention also carries extraction failures, which
  // are not submissions awaiting review. So the day is only "clear" when neither
  // has anything, or the surface could print "That's everything" directly above
  // a NEEDS YOU section listing work.
  const clear = isClearDay(view) && attentionItems.length === 0;

  // Before any class exists the only useful thing on this surface is the way to
  // make one — every other section would be an honest but useless absence.
  if (view.class_count === 0) return <Welcome headline={line1} />;

  const exceptions = view.classes.filter((c) => c.status !== "on_track");
  const healthy = view.classes.filter((c) => c.status === "on_track");

  return (
    <div className="space-y-8">
      {/* The verdict is the first thing read and the primary target. */}
      <PageHeader
        eyebrow={todayLabel()}
        title={line1}
        documentTitle="Today"
        description={line2 ?? undefined}
        actions={
          <>
            <Button variant="secondary" onClick={() => setCreateOpen(true)}>
              <CalendarPlus aria-hidden className="h-4 w-4" />
              Schedule a lesson
            </Button>
            {view.review_count > 0 && (
              <Link to="/tutor/review" className={buttonClasses("primary")}>
                Review marking
              </Link>
            )}
          </>
        }
      />

      {/* Class strip. Healthy classes collapse to one line so the exceptions are
          what the eye lands on — nothing is hidden, it is summarised. */}
      <Section title="Classes">
        <ul>
          {exceptions.map((row) => (
            <ClassRow key={row.group_id} row={row} />
          ))}
          {healthy.length > 0 && (
            <li className="border-t border-line py-2.5 text-sm text-ink-500">
              <span className="text-ok-700">●</span>{" "}
              {healthy.length === 1
                ? `${healthy[0].name} is on track`
                : `${healthy.length} classes on track`}
              <span className="ml-2 text-ink-500">
                {healthy
                  .map((c) =>
                    c.predicted_grade ? `${c.name} · Grade ${c.predicted_grade}` : c.name,
                  )
                  .join("  ·  ")}
              </span>
            </li>
          )}
        </ul>
      </Section>

      {!clear && (
        <Section title="Today">
          {view.lessons.length === 0 ? (
            <p className="text-sm text-ink-500">No lessons scheduled.</p>
          ) : (
            <ul className="text-sm">
              {view.lessons.map((lesson) => (
                <li key={lesson.id} className="flex items-center gap-3 border-t border-line py-3.5">
                  <span className="font-display tabular-nums text-ink-900">
                    {lesson.start_time.slice(0, 5)}
                  </span>
                  <Link
                    to={`/tutor/groups/${lesson.group_id}/students`}
                    className="font-medium text-ink-900 hover:text-brand-600"
                  >
                    {lesson.group_name}
                  </Link>
                  <span className="text-ink-500">{lesson.subject_name}</span>
                </li>
              ))}
            </ul>
          )}
        </Section>
      )}

      {/* WHAT CHANGED reads the stored narrative — present on open, never a
          surface waiting on a model call (spec §8). Suppressed on a clear day,
          where the terminal sentence below is the whole message. */}
      {!clear && <ClassNarrative classes={view.classes} />}

      {/* Gated on the rows it renders, not on review_count: the count comes from
          the aggregate and the rows from a separate query, so while that query
          loads (or if it resolves empty) the old condition rendered a heading
          over an empty list — the empty panel UX-29 forbids. */}
      {attentionItems.length > 0 && (
        <Section title="Needs you">
          <ul className="text-sm">
            {attentionItems.map((item, i) => (
              <li
                key={i}
                className="flex flex-wrap items-center justify-between gap-2 border-t border-line py-2.5"
              >
                <Link
                  to={
                    item.submission_id
                      ? `/tutor/submissions/${item.submission_id}`
                      : `/tutor/assignments/${item.assignment_id}`
                  }
                  className="font-medium text-brand-600 hover:text-brand-700"
                >
                  {item.assignment_title}
                </Link>
                <span className="text-warn-700">{REASON_LABELS[item.reason] ?? item.reason}</span>
              </li>
            ))}
          </ul>
          <Link
            to="/tutor/review"
            className="mt-3 inline-block text-sm font-medium text-brand-600 hover:text-brand-700"
          >
            Open the review queue →
          </Link>
        </Section>
      )}

      {clear && <p className="text-sm text-ink-500">That's everything. Enjoy your day.</p>}

      <CreateLessonModal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        groups={groups.data}
        onCreated={() => showToast("Lesson scheduled.")}
      />
      {toast}
    </div>
  );
}

/** "Thursday 2 October" — the day this page is about, in the reader's locale. */
function todayLabel(): string {
  return new Date().toLocaleDateString(undefined, {
    weekday: "long",
    day: "numeric",
    month: "long",
  });
}

const SETUP_STEPS = [
  {
    icon: BookOpen,
    title: "Add your subject's syllabus",
    body: "Upload the exam board's syllabus PDF. avora drafts its chapters and topics for you to check — homework and readiness are tracked against them.",
    to: "/tutor/syllabuses",
    cta: "Upload a syllabus",
  },
  {
    icon: Ruler,
    title: "Set your grade boundaries",
    body: "The percentage each grade starts at. Predicted grades are read through these — never invented by the AI.",
    to: "/tutor/boundaries",
    cta: "Set boundaries",
  },
  {
    icon: Users,
    title: "Create a class and invite students",
    body: "Each class gets a join code. Share it with your students; parents get a private link to follow their own child.",
    to: "/tutor/classes",
    cta: "Create a class",
  },
] as const;

/**
 * A new tutor's first screen. Before any class exists every section of Today
 * would be an honest absence, so this replaces them with the setup path, in the
 * order the experience spec fixes (subject and syllabus, boundaries, class —
 * §7). It links to the existing pages rather than enforcing an order; the
 * blocking, server-tracked onboarding of spec §9.1 is a later phase.
 */
function Welcome({ headline }: { headline: string }) {
  return (
    <div>
      <PageHeader
        eyebrow="Welcome to avora"
        title="Let's set up your first class."
        documentTitle="Today"
        description={
          <>
            <span>{headline}</span> Three steps get you from an empty account to marked homework and
            live readiness — about ten minutes.
          </>
        }
      />
      <ol className="grid gap-4 lg:grid-cols-3">
        {SETUP_STEPS.map(({ icon: Icon, title, body, to, cta }, i) => (
          <li
            key={title}
            className="flex flex-col rounded-xl border border-line bg-surface p-6 shadow-[0_1px_2px_rgba(44,26,14,0.06)]"
          >
            <div className="flex items-center justify-between">
              <span className="grid h-10 w-10 place-items-center rounded-lg bg-brand-50 text-brand-600">
                <Icon aria-hidden className="h-5 w-5" />
              </span>
              <span className="font-display text-sm text-ink-500">Step {i + 1}</span>
            </div>
            <h2 className="mt-5 font-sans text-base font-semibold text-ink-900">{title}</h2>
            <p className="mt-2 flex-1 text-sm leading-relaxed text-ink-500">{body}</p>
            <Link
              to={to}
              className={buttonClasses(
                i === SETUP_STEPS.length - 1 ? "primary" : "secondary",
                "md",
                "mt-5 self-start",
              )}
            >
              {cta}
              <ChevronRight aria-hidden className="h-4 w-4" />
            </Link>
          </li>
        ))}
      </ol>
      <p className="mt-6 text-sm text-ink-500">
        Then set the first homework from your class page — students hand it in by taking a photo.
      </p>
    </div>
  );
}
