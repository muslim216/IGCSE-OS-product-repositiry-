import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { CalendarPlus } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { todayOverview, todayView } from "../../api/today";
import { listGroups } from "../../api/groups";
import { myOrganization } from "../../api/auth";
import { useMyTimezone } from "../../auth/AuthContext";
import { assignmentsNeedingAttention } from "../../api/homework";
import { useToast } from "../../components/ui";
import { Button, buttonClasses } from "../../components/controls";
import { ErrorState, PageHeader, PageSkeleton } from "../../components/page";
import { EmptyState, SectionCard } from "../../components/ui";
import { useOnboarding } from "../../lib/onboarding";
import OnboardingFlow from "../onboarding/OnboardingFlow";
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
  // Counts acknowledgements from the setup card; see the status region below.
  const [setupSaves, setSetupSaves] = useState(0);
  const { toast, showToast } = useToast();

  // What decides whether this page is the setup flow (9.1c). The server says
  // (`in_flow`, SEC-10); this only reads it.
  const onboarding = useOnboarding();
  const inFlow = onboarding.data?.in_flow === true;
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
  useEffect(() => {
    if (!onboarding.isLoading) setOnboardingSettled(true);
  }, [onboarding.isLoading]);
  // The dashboard's own reads wait for the onboarding answer and are not made
  // while the flow is on screen: nothing in the flow uses them. Once the answer
  // is in (data or failure) they run exactly as before, so a failed onboarding
  // read still lands on a dashboard that loads.
  const dashboardEnabled = (onboardingSettled || !onboarding.isLoading) && !inFlow;

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

  if (onboarding.isLoading && !onboardingSettled) {
    return <PageSkeleton rows={3} label="Loading today" />;
  }
  // A failed or malformed onboarding read falls through to the dashboard as it
  // was before the flow existed: a read that failed must not trap a tutor on a
  // home they cannot use. The Setup card says on its own that it did not load.
  if (inFlow && onboarding.data) return <OnboardingFlow data={onboarding.data} />;

  if (today.isLoading) return <PageSkeleton rows={3} label="Loading today" />;

  if (today.isError || !today.data) {
    return (
      <>
        <ErrorState
          title="Today couldn't be loaded"
          error={today.error}
          onRetry={() => {
            void today.refetch();
            // The onboarding read may be what failed: the home also hangs on it.
            void onboarding.refetch();
          }}
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

  // Only reached when the onboarding read failed (otherwise a tutor with no class
  // is in the flow): every section below would be an honest but useless absence,
  // so say so plainly and point at where a class begins.
  if (view.class_count === 0) {
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

  // The class the accepted plan belongs to, read from the state that ended the flow.
  const acceptedClass = sawFlow
    ? onboarding.data?.subjects
        .flatMap((s) => s.classes)
        .find((c) => c.steps.some((st) => st.key === "plan_accepted" && st.done))
    : undefined;

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

      {/* Not in the flow: while a tutor is in it, the flow is the setup path. */}
      <SetupChecklist onAcknowledged={() => setSetupSaves((n) => n + 1)} />

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
