import { Link } from "react-router-dom";
import type { WeekGlance as Week } from "../../api/today";

/** A measurement with nothing behind it says so in words — never 0, 0% or an
    empty bar (PROD-2, UX-19). */
function Figure({
  label,
  value,
  note,
  to,
}: {
  label: string;
  value: string;
  note?: string;
  to?: string;
}) {
  const body = (
    <>
      <dt className="text-xs text-ink-500">{label}</dt>
      <dd className="mt-1 font-display text-lg text-ink-900">{value}</dd>
      {note && <dd className="mt-0.5 text-xs text-ink-500">{note}</dd>}
    </>
  );
  return (
    <div className="rounded-lg border border-line bg-surface px-4 py-3">
      {to ? (
        <Link to={to} className="block hover:text-brand-600">
          {body}
        </Link>
      ) : (
        body
      )}
    </div>
  );
}

/**
 * The estimate in words. "Roughly" is load-bearing (AV-101): the question count
 * is real, the time is a per-question figure the owner chose, and nothing in
 * Avora times a tutor marking. Never print these minutes without it.
 */
export function roughMarkingTime(minutes: number): string {
  if (minutes < 60) {
    const rounded = Math.max(5, Math.round(minutes / 5) * 5);
    return `roughly ${rounded} minutes`;
  }
  const hours = Math.round(minutes / 30) / 2;
  return `roughly ${hours} ${hours === 1 ? "hour" : "hours"}`;
}

/**
 * The week at a glance: lessons, marking, attendance, readiness. Each figure
 * is read from the same definition its own page uses (the server's overview),
 * and says what it was counted from.
 */
export default function WeekGlance({ week }: { week: Week }) {
  const marked = week.attendance_present + week.attendance_absent;
  return (
    <section aria-labelledby="week-heading">
      <h2 id="week-heading" className="avora-label mb-3">
        This week
      </h2>
      <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Figure
          label="Lessons"
          value={
            week.lessons_planned === 0
              ? "No lessons this week"
              : `${week.lessons_taught} of ${week.lessons_planned} taught`
          }
        />
        <Figure
          label="Marking waiting"
          value={
            week.marking_waiting === 0
              ? "Nothing waiting"
              : `${week.marking_waiting} ${week.marking_waiting === 1 ? "piece" : "pieces"}`
          }
          to={week.marking_waiting > 0 ? "/tutor/review" : undefined}
        />
        <Figure
          label="Attendance"
          value={
            week.attendance_rate == null
              ? "No attendance taken this week"
              : `${Math.round(week.attendance_rate * 100)}% present`
          }
          note={
            week.attendance_rate == null
              ? undefined
              : `${week.attendance_present} of ${marked} marked${
                  week.attendance_not_taken > 0
                    ? ` · ${week.attendance_not_taken} not taken, left out`
                    : ""
                }`
          }
        />
        <Figure
          label="Readiness since last week"
          value={
            week.readiness_compared_count === 0
              ? "No history to compare yet"
              : week.readiness_drop_count === 0
                ? "No drops"
                : `${week.readiness_drop_count} ${
                    week.readiness_drop_count === 1 ? "student" : "students"
                  } dropped`
          }
          note={
            week.readiness_compared_count === 0
              ? undefined
              : `${week.readiness_drop_threshold}+ points, of ${week.readiness_compared_count} compared`
          }
        />
      </dl>
      {/* The one piece of good news on this page (AV-101). Absent, not "0
          questions", when nothing was marked for them (PROD-2). */}
      {week.auto_marked_questions > 0 && week.auto_marked_estimate_minutes != null && (
        <p className="mt-3 text-sm text-ink-700">
          {week.auto_marked_questions} {week.auto_marked_questions === 1 ? "question" : "questions"}{" "}
          marked for you this week — {roughMarkingTime(week.auto_marked_estimate_minutes)} of
          marking.{" "}
          <span className="text-ink-500">
            An estimate, at {week.auto_marked_minutes_per_question} minutes a question.
          </span>
        </p>
      )}
    </section>
  );
}
