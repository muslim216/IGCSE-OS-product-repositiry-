import { useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { CalendarPlus } from "lucide-react";
import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import { todayOverview, todayView, type TodayOverview, type TodayView } from "../../api/today";
import type { OnboardingState } from "../../api/onboarding";
import type { Dismissals } from "../../lib/dismissals";
import { listGroups, type Group } from "../../api/groups";
import { myOrganization } from "../../api/auth";
import { useMyTimezone } from "../../auth/AuthContext";
import { assignmentsNeedingAttention, type AssignmentAttention } from "../../api/homework";
import { useToast } from "../../components/ui";
import { Button, buttonClasses } from "../../components/controls";
import { EmbeddedPageContext, ErrorState, PageHeader, PageSkeleton } from "../../components/page";
import { EmptyState, SectionCard } from "../../components/ui";
import { useOnboarding } from "../../lib/onboarding";
import { useDismissals, useReportHidden } from "../../lib/dismissals";
import { DismissalStatus, HiddenFooter } from "../../components/NotNow";
import OnboardingFlow from "../onboarding/OnboardingFlow";
import { GUIDE_KEY, guideIsGone, guideModel } from "../onboarding/guideModel";
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
  // What decides whether this page is the setup flow (9.1c). The server says
  // (`in_flow`, SEC-10); this only reads it.
  const onboarding = useOnboarding();
  // What the tutor has put aside with "Not now". While it loads, or if it fails,
  // nothing is hidden: the page is what it was before this existed.
  const dismissals = useDismissals();
  // The server says the tutor is in the flow; the tutor may have put the whole
  // guide, or every step still left in it, aside (owner, 2026-10-06). Then this is
  // the ordinary Overview, which for a tutor with no class is its no-class state.
  // In the flow, whether the guide is shown depends on the list: hold that
  // decision until it has loaded or failed (failing shows everything).
  const deciding = onboarding.data?.in_flow === true && !dismissals.settled;
  const guideGone = onboarding.data ? guideIsGone(onboarding.data, dismissals.isHidden) : false;
  const inFlow = onboarding.data?.in_flow === true && !guideGone;
  const status = <DismissalStatus dismissals={dismissals} />;
  // What the guide has put aside: the whole guide, or steps still asked for.
  useReportHidden(
    dismissals,
    "guide",
    onboarding.data?.in_flow
      ? [
          ...(dismissals.isHidden(GUIDE_KEY) ? [GUIDE_KEY] : []),
          ...guideModel(onboarding.data, dismissals.isHidden).skippedKeys,
        ]
      : [],
  );
  const footer = <HiddenFooter dismissals={dismissals} />;
  // Per visit, in component state: the line below shows when this page has just
  // changed from the flow to the dashboard, and is gone on the next visit.
  const [sawFlow, setSawFlow] = useState(false);
  useEffect(() => {
    if (inFlow) setSawFlow(true);
  }, [inFlow]);

  // Skeleton on the first answer only. A failed read is retried when the Setup
  // card below mounts and reads the same query, which puts it back to "loading":
  // gating on that would unmount the card, fail again, and loop.
  const [onboardingSettled, setOnboardingSettled] = useState(false);
  const onboardingPending = onboarding.isLoading && !onboardingSettled;
  useEffect(() => {
    if (!onboarding.isLoading) setOnboardingSettled(true);
  }, [onboarding.isLoading]);
  // A tutor in the flow who already runs a class keeps the dashboard underneath
  // it (owner, 2026-10-06): every tutor without an accepted plan is in the flow,
  // and replacing the page for one with lessons today would take away the agenda,
  // the reminders and the way to schedule a lesson, none of which live anywhere
  // else. It would also strand a class that cannot get a plan (everything already
  // taught, or the exam too close) on a page with nothing else on it.
  const hasClass = onboarding.data?.subjects.some((s) => s.classes.length > 0) ?? false;
  const flowAlone = inFlow && !hasClass && !deciding;
  // The dashboard's own reads stop once the server says this tutor is in the
  // flow with no class, where nothing shows them. They are NOT held back while
  // that answer is still loading: this is the most-viewed page, and waiting would
  // put an extra round trip in front of it for every tutor on every visit, to
  // save a new tutor one set of requests once.
  const dashboardEnabled = !flowAlone;

  const today = useQuery({ queryKey: ["today"], queryFn: todayView, enabled: dashboardEnabled });
  // The overview feeds the week strip, the agenda and the cards. Polled so
  // "in 10 min" and a lesson that has just ended are never long out of date.
  const overview = useQuery({
    queryKey: ["today-overview"],
    queryFn: todayOverview,
    refetchInterval: 60_000,
    enabled: dashboardEnabled,
  });
  const attention = useQuery({
    queryKey: ["assignments-attention"],
    queryFn: assignmentsNeedingAttention,
    enabled: dashboardEnabled,
  });
  // Only the lesson modal needs full Group objects; the surface itself renders
  // from the aggregate, so this never gates what the tutor reads.
  const groups = useQuery({ queryKey: ["groups"], queryFn: listGroups, enabled: dashboardEnabled });
  // The zone the API decided "today" in: the tutor's own override, else the
  // organization's, else UTC (`effective_timezone`). The organization is only
  // asked for when there is no override to win over it.
  const myZone = useMyTimezone();
  const org = useQuery({
    queryKey: ["my-organization"],
    queryFn: myOrganization,
    enabled: !myZone && dashboardEnabled,
  });
  const dayZone = myZone || (org.isSuccess ? org.data.timezone || "UTC" : null);

  const body = renderBody({
    onboarding,
    today,
    overview,
    attention,
    groups: groups.data,
    dayZone,
    dismissals,
    flags: { inFlow, flowAlone, deciding, sawFlow, onboardingPending },
  });

  // Rendered here, once, around every state the page can be in: the same DOM
  // nodes survive a change of branch, so the live region is not remounted holding
  // text (which is often not read) and focus placed on it is not lost. The footer
  // is the way back for everything hidden above, in the setup guide and checklist,
  // the plan prompts and the lesson reminders. Not "Needs you", which has no "Not
  // now" at all: hiding it would let a student's work silently never be marked.
  return (
    <>
      {body}
      {footer}
      {status}
    </>
  );
}

type Flags = {
  inFlow: boolean;
  flowAlone: boolean;
  deciding: boolean;
  sawFlow: boolean;
  onboardingPending: boolean;
};

type BodyContext = {
  onboarding: UseQueryResult<OnboardingState>;
  today: UseQueryResult<TodayView>;
  overview: UseQueryResult<TodayOverview>;
  attention: UseQueryResult<AssignmentAttention[]>;
  groups: Group[] | undefined;
  dayZone: string | null;
  dismissals: Dismissals;
  flags: Flags;
};

const SKELETON = <PageSkeleton rows={3} label="Loading overview" />;

/** Which state the page is in, one at a time. The status line and footer are
 *  rendered by the caller around this, so they are the same nodes in every state. */
function renderBody(ctx: Readonly<BodyContext>) {
  const { onboarding, today, dismissals, flags } = ctx;
  if (flags.onboardingPending) return SKELETON;
  // A failed or malformed onboarding read falls through to the dashboard as it
  // was before the flow existed: a read that failed must not trap a tutor on a
  // home they cannot use. The Setup card says on its own that it did not load.
  // A tutor in the flow waits here for the hidden list, so the guide is never
  // shown and then taken away; the dashboard's reads are already running.
  if (flags.deciding) return SKELETON;
  if (flags.flowAlone && onboarding.data) {
    // Same shape as the states below (the guide, then what follows it), so React
    // keeps the one guide instance, with its announcements and focus, when a class
    // appears and the dashboard starts to load under it.
    return (
      <>
        <OnboardingFlow data={onboarding.data} dismissals={dismissals} />
        {null}
      </>
    );
  }
  // Above every state of the dashboard, a failed one included: the guide reads
  // its own data and must not disappear because the home aggregate did not load.
  const flow =
    flags.inFlow && onboarding.data ? (
      <OnboardingFlow data={onboarding.data} overDashboard dismissals={dismissals} />
    ) : null;

  if (today.isLoading) {
    return (
      <>
        {flow}
        {SKELETON}
      </>
    );
  }
  if (today.isError || !today.data) {
    return (
      <>
        {flow}
        <ErrorState
          title="Overview couldn't be loaded"
          error={today.error}
          onRetry={() => {
            void today.refetch();
            // The onboarding read may be what failed: the home also hangs on it.
            void onboarding.refetch();
          }}
        />
        {/* Fetches its own data: a lesson about to start must not hide behind a
            failed home aggregate. */}
        <LessonReminders dismissals={dismissals} />
      </>
    );
  }
  // Only reached when the onboarding read failed, or the tutor put the setup
  // guide aside with "Not now" (otherwise a tutor with no class is in the flow):
  // every section below would be an honest but useless absence, so say so
  // plainly and point at where a class begins.
  if (today.data.class_count === 0) {
    return (
      <>
        {flow}
        <NoClasses />
      </>
    );
  }
  return <DashboardMain ctx={ctx} view={today.data} flow={flow} />;
}

function NoClasses() {
  return (
    <SectionCard>
      <EmptyState
        title="No classes yet."
        hint="A class starts from a subject's syllabus."
        action={
          <Link to="/tutor/subject-setup" className={buttonClasses("primary")}>
            Open Subject setup
          </Link>
        }
      />
    </SectionCard>
  );
}

/** The class the accepted plan belongs to, read from the state that ended the flow. */
function acceptedClassOf(onboarding: OnboardingState | undefined, sawFlow: boolean) {
  if (!sawFlow) return undefined;
  return onboarding?.subjects
    .flatMap((s) => s.classes)
    .find((c) => c.steps.some((st) => st.key === "plan_accepted" && st.done));
}

function QuietRetry({ children, onRetry }: Readonly<{ children: string; onRetry: () => void }>) {
  return (
    <p role="status" className="flex items-center gap-2 text-sm text-ink-500">
      {children}
      <Button type="button" size="sm" variant="ghost" onClick={onRetry}>
        Retry
      </Button>
    </p>
  );
}

function DashboardMain({
  ctx,
  view,
  flow,
}: Readonly<{ ctx: BodyContext; view: TodayView; flow: ReactNode }>) {
  const { onboarding, overview, attention, dayZone, dismissals, flags } = ctx;
  const [createOpen, setCreateOpen] = useState(false);
  // Counts acknowledgements from the setup card; see the status region below.
  const [setupSaves, setSetupSaves] = useState(0);
  const { toast, showToast } = useToast();

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
  const acceptedClass = acceptedClassOf(onboarding.data, flags.sawFlow);

  return (
    <div className="space-y-8">
      {/* Always mounted so the change is announced. A second save alternates a
        trailing space so the same sentence is read again. */}
      <p role="status" className="sr-only">
        {setupSaves > 0 ? `Saved. Setup updated.${setupSaves % 2 ? "" : "\u00a0"}` : ""}
      </p>
      {acceptedClass && (
        <p className="rounded-lg bg-surface-muted px-4 py-3 text-sm text-ink-700">
          Your teaching plan is accepted. Students can be added from the class page.{" "}
          <Link
            to={`/tutor/groups/${acceptedClass.group_id}/students`}
            className="text-brand-600 hover:underline"
          >
            Open the Students tab for {acceptedClass.group_name}
          </Link>
        </p>
      )}
      {flow}
      {/* The verdict is the first thing read and the primary target. Under the
        guide it is a section heading: the guide holds the page's one h1. */}
      <EmbeddedPageContext.Provider value={flow ? "overview-verdict" : false}>
        <PageHeader
          eyebrow={dayZone ? todayLabel(dayZone) : undefined}
          title={line1}
          documentTitle="Overview"
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
      </EmbeddedPageContext.Provider>

      {/* Not in the flow: while a tutor is in it, the flow is the setup path. */}
      {!flow && (
        <SetupChecklist
          onAcknowledged={() => setSetupSaves((n) => n + 1)}
          dismissals={dismissals}
        />
      )}

      {overview.data ? (
        <WeekGlance week={overview.data.week} />
      ) : (
        overview.isError && (
          <QuietRetry onRetry={() => overview.refetch()}>
            Couldn't load this week and today's lessons.
          </QuietRetry>
        )
      )}

      {overview.data && <TodayAgenda items={overview.data.agenda} />}

      <ClassCards rows={view.classes} cards={overview.data?.classes} />

      {/* Not suppressed on a clear day: it is about next week's preparation, not
        today's backlog, and the lookahead is its whole point. */}
      <ChapterPrompts prompts={view.chapter_prompts ?? []} dismissals={dismissals} />

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
        <QuietRetry onRetry={() => attention.refetch()}>Couldn't check what needs you.</QuietRetry>
      )}
      <NeedsYou items={attentionItems} remarks={remarks} />

      {showSignOff && <p className="text-sm text-ink-500">That's everything. Enjoy your day.</p>}

      <CreateLessonModal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        groups={ctx.groups}
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
