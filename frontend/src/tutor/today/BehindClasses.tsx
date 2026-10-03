import { Link } from "react-router-dom";
import type { BehindClass } from "../../api/today";

/** "Tue 6 Oct". The plan's dates are calendar dates with no zone, so they are
    read from the parts rather than `new Date(iso)`, which parses a bare date as
    UTC midnight and can print the day before. */
function shortDate(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString(undefined, {
    weekday: "short",
    day: "numeric",
    month: "short",
  });
}

/**
 * Classes whose accepted plan has lessons dated before today with none recorded
 * (task 6.6, AV-18). Says "not recorded", never "missed": a lesson may have been
 * taught and not logged. Information with a link to the plan, where the re-plan
 * lives — nothing here changes anything. Renders nothing when there are none
 * (UX-29).
 */
export default function BehindClasses({ classes }: { classes: BehindClass[] }) {
  if (classes.length === 0) return null;
  return (
    <section aria-labelledby="behind-classes-heading">
      <h2 id="behind-classes-heading" className="avora-label mb-3">
        Plan check
      </h2>
      <ul className="text-sm">
        {classes.map((c) => (
          <li
            key={c.group_id}
            className="flex flex-wrap items-center justify-between gap-2 border-t border-line py-2.5"
          >
            <span className="text-ink-700">
              <span className="font-medium text-ink-900">{c.group_name}</span>: {c.missed} planned{" "}
              {c.missed === 1 ? "lesson hasn't" : "lessons haven't"} been recorded since{" "}
              {shortDate(c.earliest_missed_date)}
              <span className="text-ink-500">
                {" "}
                — starting with Chapter {c.chapter_code} · {c.chapter_title}
              </span>
            </span>
            <Link
              to={`/tutor/groups/${c.group_id}/schedule`}
              className="font-medium text-brand-600 hover:text-brand-700"
            >
              Review the plan →
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
