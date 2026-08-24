import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { WEEKDAYS, myLessons } from "../api/groups";
import { myReadiness } from "../api/readiness";
import { myAssignments } from "../api/homework";
import { DirectionMark, EmptyState } from "../components/ui";
import MyTimezoneSetting from "../components/MyTimezoneSetting";
import { ABSENT } from "../lib/labels";
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
    <li className="flex items-baseline gap-2 rounded-lg border border-line bg-surface px-3 py-2">
      <span className="text-sm font-medium text-ink-900">{name}</span>
      {score === null ? (
        // Absent is words. A subject with no confident evidence is not a zero,
        // and it is not an empty bar either (PROD-2, UX-19).
        <span className="text-xs text-ink-500">{ABSENT.noEvidence}</span>
      ) : (
        <>
          <span className="font-display text-lg tabular-nums text-ink-900">{score}</span>
          <DirectionMark direction={direction} />
        </>
      )}
    </li>
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
  if (!dueAt) return "no due date";
  const days = calendarDaysUntil(dueAt, timeZone);
  if (days < 0) return "overdue";
  if (days === 0) return "due today";
  if (days === 1) return "due tomorrow";
  return `due ${formatDayMonth(new Date(dueAt), timeZone)}`;
}

export default function StudentHomePage() {
  // The signed-in identity already carries time_zone, so no extra request is
  // needed to know which midnight this reader's dates turn over on.
  const myZone = useMyTimezone();
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
    return (
      <div className="space-y-6" aria-busy="true">
        <span aria-hidden className="block h-16 w-full animate-pulse rounded bg-surface-muted" />
        <span aria-hidden className="block h-7 w-2/3 animate-pulse rounded bg-surface-muted" />
      </div>
    );
  }

  // A failed load is stated. Rendering nothing would read as "you have no
  // subjects and nothing to do", which is a different and wrong claim.
  if (readiness.isError || assignments.isError) {
    return <EmptyState title="Your home couldn't be loaded." hint={ABSENT.loadFailed} />;
  }

  return (
    <div className="space-y-8">
      {strip.length > 0 && (
        <ul className="flex flex-wrap gap-2">
          {strip.map((s) => (
            <SubjectChip
              key={s.subject_id}
              name={s.subject_name}
              score={s.score}
              direction={s.direction}
            />
          ))}
        </ul>
      )}

      <h2 className="font-display text-2xl font-semibold text-ink-900">{dueVerdict(due.length)}</h2>

      {due.length > 0 && (
        <section>
          <h3 className="avora-label mb-2">Do</h3>
          <ul className="text-sm">
            {due.slice(0, 5).map((a) => (
              <li
                key={a.id}
                className="flex flex-wrap items-center justify-between gap-2 border-t border-line py-2.5"
              >
                <span className="text-ink-900">
                  <span className="text-ink-500">{a.subject_name} · </span>
                  {a.title}
                </span>
                <span className="flex items-center gap-3">
                  <span className="text-ink-500">{dueLabel(a.due_at, myZone)}</span>
                  <Link
                    to={`/student/homework/${a.id}`}
                    className="font-medium text-brand-600 hover:text-brand-700"
                  >
                    Start →
                  </Link>
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* Nothing to report is not a panel saying so (UX-29): with no marks in
          the last week and no subject that has moved, the section is absent. */}
      {(marked.length > 0 || gains.length > 0) && (
        <section>
          <h3 className="avora-label mb-2">You did</h3>
          <ul className="space-y-1.5 text-sm">
            {marked.map((a) => (
              <li key={a.id} className="text-ink-700">
                <span className="text-ok-700">✓</span> {a.subject_name} marked —{" "}
                <span className="tabular-nums">
                  {a.my_total}/{a.total_marks}
                </span>
                {/* The one sanctioned peer comparison on a student surface: a
                    thing that happened on a particular day, told only to the
                    student it happened to. Its absence on an ordinary day
                    carries no message, which is exactly what a standing —
                    "you are above the class average" — would not manage. */}
                {a.highest_in_class && (
                  <span className="block pl-4 text-ink-500">highest in your class on this</span>
                )}
              </li>
            ))}
            {gains.map((s) => (
              <li key={s.subject_id} className="text-ink-700">
                <span className="text-ok-700">✓</span> {s.subject_name} up{" "}
                {Math.round(s.month_delta ?? 0)} this month
              </li>
            ))}
          </ul>
        </section>
      )}

      {nextLesson && (
        <section>
          <h3 className="avora-label mb-2">Next</h3>
          <p className="text-sm text-ink-700">
            {nextLesson.subject_name} · {WEEKDAYS[nextLesson.weekday]}{" "}
            {nextLesson.start_time.slice(0, 5)}
          </p>
        </section>
      )}

      {/* The cleared state's one offer. There is no practice, quiz or revision
          generator behind any other verb, and a control with nothing behind it
          is worse than no control (§2.3) — so sitting a past paper is the whole
          menu, and it appears only when there is genuinely nothing due. */}
      {due.length === 0 && (
        <section>
          <h3 className="avora-label mb-2">If you want</h3>
          <p className="flex flex-wrap items-center gap-3 text-sm text-ink-700">
            Sit a past paper
            <Link
              to="/student/past-papers"
              className="font-medium text-brand-600 hover:text-brand-700"
            >
              Browse →
            </Link>
          </p>
        </section>
      )}

      {/* Below everything the student came for. AV-67 is written for exactly
          this reader — a student in another country from their tutor, whose
          "due today" should turn over at their own midnight, not the account's.
          A student has no settings screen yet and Phase D owns where one goes;
          until then the control lives here rather than nowhere, because a
          preference no one can reach is not a preference. */}
      <MyTimezoneSetting />
    </div>
  );
}
