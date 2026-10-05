import { useId, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { CalendarClock, Check } from "lucide-react";
import { WEEKDAYS, myLessons } from "../api/groups";
import { myReadiness } from "../api/readiness";
import { myAssignments } from "../api/homework";
import { DirectionMark, SectionCard } from "../components/ui";
import { ErrorState, PageHeader, PageSkeleton } from "../components/page";
import WeeklySendLink from "../components/WeeklySendLink";
import { ABSENT } from "../lib/labels";
import { VerdictLine } from "../components/VerdictLine";
import { greetingFor } from "../lib/readiness";
import { calendarDaysUntil, formatDayMonth } from "../lib/timezones";
import { useMyTimezone } from "../auth/AuthContext";
import { dueVerdict, monthlyGains, recentlyMarked, subjectStrip } from "../lib/student";

/**
 * The student's home: subject strip → verdict → DO → YOU DID → NEXT.
 *
 * Two rules shape every branch below.
 *
 * **No cross-subject aggregate.** This surface used to open with one "Overall
 * readiness" percentage, a plain mean over subjects with different scales,
 * different coverage and different boundaries. It was arithmetically
 * meaningless and it was the first thing a student read every day. Readiness is
 * per subject and is shown as one (experience-design §5.1).
 *
 * **Every value is paired with its direction.** `Maths 48 ↓` describes a
 * situation that can be acted on; `Maths 48` alone is a label on a person
 * (UX-31). Where there is no direction there is no arrow — never "→", which
 * would claim a movement nothing measured.
 *
 * **On ordering: DO comes before YOU DID.** experience-design §5.1 contains
 * both "DO … is never below the fold on any supported viewport" and "YOU DID
 * precedes any request for work"; on a phone those cannot both hold. Its own
 * mock puts DO first, and the implementation plan's test for this PR is named
 * for that order, so DO leads. The reward-before-request intent is kept in the
 * shape rather than the sequence: DO carries exactly what is due and nothing
 * else, so YOU DID is still visible without scrolling on a phone whenever there
 * are one or two pieces due, which is the ordinary day.
 *
 * **The verdict is the page title.** It is the one sentence UX-27 says the
 * surface opens with, so it is the <h1> rather than a line under a generic
 * "Home" heading that would push it down the screen. The subject strip stays
 * above it, as §5.1 draws it: the polish pass moved neither section. So the
 * strip's label is not a heading — an <h2> ahead of the <h1> would start the
 * page's outline at level two — and the strip is a region named by that label
 * instead, which a screen reader can still jump to.
 *
 * Personal settings (the time-zone control) used to sit at the bottom of this
 * page because a student had no settings screen. They now live on the
 * student's Account page, one tap from the avatar.
 */

function SubjectChip({
  name,
  score,
  direction,
}: {
  name: string;
  score: number | null;
  direction: "up" | "flat" | "down" | null;
}) {
  return (
    <li className="flex items-center justify-between gap-3 rounded-lg border border-line bg-surface px-4 py-3 shadow-[0_1px_2px_rgba(44,26,14,0.06)]">
      <span className="min-w-0 truncate text-sm font-medium text-ink-900">{name}</span>
      {score === null ? (
        // Absent is words. A subject with no confident evidence is not a zero,
        // and it is not an empty bar either (PROD-2, UX-19).
        <span className="shrink-0 text-xs text-ink-500">{ABSENT.noEvidence}</span>
      ) : (
        // "62% ready", never a bare "62": a number with no unit on a
        // student's home is read as a mark out of a hundred, or worse.
        <span className="flex shrink-0 items-baseline gap-1.5">
          <span className="font-display text-lg tabular-nums text-ink-900">{score}%</span>
          <span className="text-xs text-ink-500">ready</span>
          <DirectionMark direction={direction} />
        </span>
      )}
    </li>
  );
}

/** A page section: a quiet label over a card, the same shape for every block
    so the home reads as one surface rather than four. */
function HomeSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section>
      <h2 className="avora-label mb-2">{title}</h2>
      <SectionCard className="py-1">{children}</SectionCard>
    </section>
  );
}

/** "due today" in the student's own zone, not the device's (AV-67).
 *
 * The whole promise of the per-user override is that a student who has said
 * they are in Dubai gets Dubai's midnight deciding what is due today. Without
 * the zone threaded through here the setting saves and changes nothing they
 * can see, which is worse than not offering it. Unset falls back to the
 * browser's zone — the behaviour every one of these labels had before the
 * column existed. */
function dueLabel(dueAt: string | null, timeZone: string | null): string {
  if (!dueAt) return "No due date";
  const days = calendarDaysUntil(dueAt, timeZone);
  if (days < 0) return "Overdue";
  if (days === 0) return "Due today";
  if (days === 1) return "Due tomorrow";
  return `Due ${formatDayMonth(new Date(dueAt), timeZone)}`;
}

export default function StudentHomePage() {
  // The signed-in identity already carries time_zone, so no extra request is
  // needed to know which midnight this reader's dates turn over on.
  const myZone = useMyTimezone();
  const stripLabelId = useId();
  const readiness = useQuery({ queryKey: ["my-readiness"], queryFn: myReadiness });
  const lessons = useQuery({ queryKey: ["my-lessons"], queryFn: myLessons });
  const assignments = useQuery({ queryKey: ["my-assignments"], queryFn: myAssignments });

  const subjects = readiness.data?.subjects ?? [];
  const strip = subjectStrip(subjects);
  const gains = monthlyGains(subjects);

  const all = assignments.data ?? [];
  // Only open, unsubmitted work is "to do". A closed assignment with no
  // submission is not something the student can start — the submit endpoint
  // rejects it — so it must not get a Start link or inflate the day's count
  // (Qodo). Its marks still live in YOU DID via recentlyMarked below.
  const due = all.filter((a) => a.is_open && a.submission_status === "not_submitted");
  const marked = recentlyMarked(all).slice(0, 3);
  const nextLesson = lessons.data?.[0];

  if (readiness.isLoading || assignments.isLoading) {
    return <PageSkeleton rows={3} label="Loading your home" />;
  }

  // A failed load is stated. Rendering nothing would read as "you have no
  // subjects and nothing to do", which is a different and wrong claim. Either
  // request failing lands here, so the title names the one that did — "your
  // subjects" over a homework failure points the student at the wrong thing.
  if (readiness.isError || assignments.isError) {
    return (
      <div className="max-w-3xl">
        <PageHeader title="Home" />
        <ErrorState
          title={
            !assignments.isError
              ? "Couldn't load your subjects."
              : !readiness.isError
                ? "Couldn't load your homework."
                : "Couldn't load your home."
          }
          error={readiness.error ?? assignments.error}
          onRetry={() => {
            void readiness.refetch();
            void assignments.refetch();
          }}
        />
      </div>
    );
  }

  return (
    <div className="max-w-3xl space-y-6">
      {strip.length > 0 && (
        <section aria-labelledby={stripLabelId}>
          <p id={stripLabelId} className="avora-label mb-2">
            Your subjects
          </p>
          <ul className="grid gap-3 sm:grid-cols-2">
            {strip.map((s) => (
              <SubjectChip
                key={s.subject_id}
                name={s.subject_name}
                score={s.score}
                direction={s.direction}
              />
            ))}
          </ul>
        </section>
      )}

      <PageHeader
        eyebrow={greetingFor(new Date().getHours())}
        title={dueVerdict(due.length)}
        documentTitle="Home"
      />

      <WeeklySendLink home="/student" />

      {/* Homework due and the verdict are different facts, and both are shown:
          "nothing due" must never read as "all is well" when the tutor's
          verdict says otherwise (coherence C.1). */}
      {subjects.length > 0 && (
        <HomeSection title="Where you stand">
          <ul className="divide-y divide-line text-sm">
            {subjects.map((s) => (
              <li
                key={s.subject_id}
                className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 py-3"
              >
                <span className="font-medium text-ink-900">{s.subject_name}</span>
                <VerdictLine role="student" verdict={s.verdict} />
              </li>
            ))}
          </ul>
        </HomeSection>
      )}

      {due.length > 0 && (
        <HomeSection title="Do">
          <ul className="divide-y divide-line text-sm">
            {due.slice(0, 5).map((a) => (
              <li
                key={a.id}
                className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 py-3"
              >
                <span className="min-w-0">
                  <span className="block font-medium text-ink-900">{a.title}</span>
                  <span className="block text-xs text-ink-500">
                    {a.subject_name} · {dueLabel(a.due_at, myZone)}
                  </span>
                </span>
                <Link
                  to={`/student/homework/${a.id}`}
                  className="font-medium text-brand-600 hover:text-brand-700"
                >
                  Start →
                </Link>
              </li>
            ))}
          </ul>
        </HomeSection>
      )}

      {/* Nothing to report is not a panel saying so (UX-29): with no marks in
          the last week and no subject that has moved, the section is absent. */}
      {(marked.length > 0 || gains.length > 0) && (
        <HomeSection title="You did">
          <ul className="divide-y divide-line text-sm">
            {marked.map((a) => (
              <li key={a.id} className="flex gap-3 py-3">
                <Check aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-ok-700" />
                <span className="min-w-0 text-ink-700">
                  <span className="font-medium text-ink-900">{a.title}</span> marked ·{" "}
                  {a.subject_name}
                  <span className="block text-xs tabular-nums text-ink-500">
                    {a.my_total} out of {a.total_marks} marks
                  </span>
                  {/* The one sanctioned peer comparison on a student surface: a
                      thing that happened on a particular day, told only to the
                      student it happened to. Its absence on an ordinary day
                      carries no message, which is exactly what a standing —
                      "you are above the class average" — would not manage. */}
                  {a.highest_in_class && (
                    <span className="mt-1 inline-block rounded-md bg-ok-100 px-2 py-0.5 text-xs font-medium text-ok-700">
                      Highest mark in your class on this piece
                    </span>
                  )}
                </span>
              </li>
            ))}
            {gains.map((s) => (
              <li key={s.subject_id} className="flex gap-3 py-3">
                <Check aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-ok-700" />
                <span className="text-ink-700">
                  {s.subject_name} up {Math.round(s.month_delta ?? 0)} readiness points this month
                </span>
              </li>
            ))}
          </ul>
        </HomeSection>
      )}

      {nextLesson && (
        <HomeSection title="Next">
          <p className="flex items-center gap-3 py-3 text-sm text-ink-700">
            <CalendarClock aria-hidden className="h-4 w-4 shrink-0 text-brand-600" />
            <span>
              <span className="font-medium text-ink-900">{nextLesson.subject_name}</span> ·{" "}
              {WEEKDAYS[nextLesson.weekday]}{" "}
              <span className="tabular-nums">{nextLesson.start_time.slice(0, 5)}</span>
            </span>
          </p>
        </HomeSection>
      )}

      {/* The cleared state's one offer. There is no practice, quiz or revision
          generator behind any other verb, and a control with nothing behind it
          is worse than no control (§2.3) — so sitting a past paper is the whole
          menu, and it appears only when there is genuinely nothing due. */}
      {due.length === 0 && (
        <HomeSection title="If you want">
          <p className="flex flex-wrap items-center justify-between gap-3 py-3 text-sm text-ink-700">
            Sit a past paper
            <Link
              to="/student/past-papers"
              className="font-medium text-brand-600 hover:text-brand-700"
            >
              Browse →
            </Link>
          </p>
        </HomeSection>
      )}
    </div>
  );
}
