import { useState } from "react";
import { Link } from "react-router-dom";
import { BookOpen, CalendarPlus, ChevronRight, Ruler, Users } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { todayOverview, todayView } from "../../api/today";
import { listGroups } from "../../api/groups";
import { myOrganization } from "../../api/auth";
import { useMyTimezone } from "../../auth/AuthContext";
import { assignmentsNeedingAttention } from "../../api/homework";
import { useToast } from "../../components/ui";
import { Button, buttonClasses } from "../../components/controls";
import { ErrorState, PageHeader, PageSkeleton } from "../../components/page";
import { isClearDay, verdictLine1, verdictLine2 } from "../../lib/verdict";
import LessonReminders from "./LessonReminders";
import ChapterPrompts from "./ChapterPrompts";
import ClassCards from "./ClassCards";
import WeeklySendLink from "../../components/WeeklySendLink";
import ClassNarrative from "./ClassNarrative";
import CreateLessonModal from "./CreateLessonModal";
import NeedsYou from "./NeedsYou";
import SetupChecklist from "./SetupChecklist";
import TodayAgenda from "./TodayAgenda";
import WeekGlance from "./WeekGlance";

/**
 * The tutor's Overview: verdict → week at a glance → today's agenda → class
 * cards → what changed → needs you.
 *
 * The rule that shapes every branch below: a section with nothing to report is
 * NOT RENDERED (UX-29) unless saying so is the answer ("No lessons scheduled
 * today."). It never becomes an empty card, or a `0` standing in for a missing
 * measurement (PROD-2, UX-19). A completely clear day ends with a sentence.
 *
 * Plan-check and classified prompts: the "N lessons behind" text and its fix
 * moved onto each class card (it was a separate "Plan check" list); the
 * "coming up" prompts about missing classifieds are not on a card and stay.
 */
export default function TodayDashboard() {
  const [createOpen, setCreateOpen] = useState(false);
  const { toast, showToast } = useToast();

  const today = useQuery({ queryKey: ["today"], queryFn: todayView });
  // The overview feeds the week strip, the agenda and the cards. Polled so
  // "in 10 min" and a lesson that has just ended are never long out of date.
  const overview = useQuery({
    queryKey: ["today-overview"],
    queryFn: todayOverview,
    refetchInterval: 60_000,
  });
  const attention = useQuery({
    queryKey: ["assignments-attention"],
    queryFn: assignmentsNeedingAttention,
  });
  // Only the lesson modal needs full Group objects; the surface itself renders
  // from the aggregate, so this never gates what the tutor reads.
  const groups = useQuery({ queryKey: ["groups"], queryFn: listGroups });
  // The zone the API decided "today" in: the tutor's own override, else the
  // organization's, else UTC (`effective_timezone`). The organization is only
  // asked for when there is no override to win over it.
  const myZone = useMyTimezone();
  const org = useQuery({
    queryKey: ["my-organization"],
    queryFn: myOrganization,
    enabled: !myZone,
  });
  const dayZone = myZone || (org.isSuccess ? org.data.timezone || "UTC" : null);

  if (today.isLoading) return <PageSkeleton rows={3} label="Loading today" />;

  if (today.isError || !today.data) {
    return (
      <>
        <ErrorState
          title="Today couldn't be loaded"
          error={today.error}
          onRetry={() => today.refetch()}
        />
        {/* Fetches its own data: a lesson about to start must not hide behind a
            failed home aggregate. */}
        <LessonReminders />
      </>
    );
  }

  const view = today.data;
  const line1 = verdictLine1(view);
  const line2 = verdictLine2(view);
  const attentionItems = attention.data ?? [];
  const remarks = overview.data?.remarks ?? [];
  // The aggregate's review_count and the attention list are different measures
  // from different endpoints — attention also carries extraction failures, which
  // are not submissions awaiting review. So the day is only "clear" when neither
  // has anything, or the surface could print "That's everything" directly above
  // a NEEDS YOU section listing work.
  //
  // And only when both reads actually succeeded: a failed read is not an empty
  // one, so the sign-off must not be printed over a Needs-you list we could not
  // load (PROD-2).
  const loaded = overview.isSuccess && attention.isSuccess;
  const clear = loaded && isClearDay(view) && attentionItems.length === 0 && remarks.length === 0;
  // Classes with lessons not recorded against their plan keep the sign-off from
  // being printed, but do not change which sections open (task 6.6).
  const showSignOff = clear && (view.behind_classes ?? []).length === 0;

  // Before any class exists the only useful thing on this surface is the way to
  // make one — every other section would be an honest but useless absence.
  if (view.class_count === 0) return <Welcome headline={line1} />;

  return (
    <div className="space-y-8">
      {/* The verdict is the first thing read and the primary target. */}
      <PageHeader
        eyebrow={dayZone ? todayLabel(dayZone) : undefined}
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

      {/* Not in Welcome: before any class exists that surface is the setup path. */}
      <SetupChecklist />

      {overview.data ? (
        <WeekGlance week={overview.data.week} />
      ) : (
        overview.isError && (
          <p role="status" className="flex items-center gap-2 text-sm text-ink-500">
            Couldn&apos;t load this week and today&apos;s lessons.
            <Button type="button" size="sm" variant="ghost" onClick={() => overview.refetch()}>
              Retry
            </Button>
          </p>
        )
      )}

      {overview.data && <TodayAgenda items={overview.data.agenda} />}

      <ClassCards rows={view.classes} cards={overview.data?.classes} />

      {/* Not suppressed on a clear day: it is about next week's preparation, not
          today's backlog, and the lookahead is its whole point. */}
      <ChapterPrompts prompts={view.chapter_prompts ?? []} />

      {/* WHAT CHANGED reads the stored narrative — present on open, never a
          surface waiting on a model call (spec §8). Suppressed on a clear day,
          where the terminal sentence below is the whole message. */}
      {!clear && <ClassNarrative classes={view.classes} />}

      {/* A link into the stored weekly send, not a copy of it (AV-51). */}
      <WeeklySendLink home="/tutor" />

      {/* Gated on the rows it renders, not on review_count: the count comes from
          the aggregate and the rows from separate queries, so while those load
          (or resolve empty) a heading over an empty list is the empty panel
          UX-29 forbids. */}
      {attention.isError && (
        <p role="status" className="flex items-center gap-2 text-sm text-ink-500">
          Couldn&apos;t check what needs you.
          <Button type="button" size="sm" variant="ghost" onClick={() => attention.refetch()}>
            Retry
          </Button>
        </p>
      )}
      <NeedsYou items={attentionItems} remarks={remarks} />

      {showSignOff && <p className="text-sm text-ink-500">That's everything. Enjoy your day.</p>}

      <CreateLessonModal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        groups={groups.data}
        onCreated={() => {
          showToast("Lesson scheduled.");
        }}
      />
      {toast}
    </div>
  );
}

/** "Thursday 2 October" — the day this page is about, in the reader's locale.
 *
 * Dated in the zone the lessons below were chosen in, not the browser's: a
 * tutor whose device clock and organization disagree across midnight was shown
 * one day's date over another day's lessons. Until that zone is known the
 * eyebrow is left out rather than guessed. A zone the browser cannot load
 * falls back to UTC, which is what the server does with it too (`now_in`). */
function todayLabel(timeZone: string): string {
  const options: Intl.DateTimeFormatOptions = { weekday: "long", day: "numeric", month: "long" };
  try {
    return new Date().toLocaleDateString(undefined, { ...options, timeZone });
  } catch {
    return new Date().toLocaleDateString(undefined, { ...options, timeZone: "UTC" });
  }
}

const SETUP_STEPS = [
  {
    icon: BookOpen,
    title: "Add your subject's syllabus",
    body: "Upload the exam board's syllabus PDF. avora drafts its chapters and topics for you to check — homework and readiness are tracked against them.",
    to: "/tutor/subject-setup#syllabus",
    cta: "Upload a syllabus",
  },
  {
    icon: Ruler,
    title: "Set your grade boundaries",
    body: "The percentage each grade starts at. Predicted grades are read through these — never invented by the AI.",
    to: "/tutor/subject-setup#boundaries",
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
