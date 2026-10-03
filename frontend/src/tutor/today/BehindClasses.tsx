import { Link } from "react-router-dom";
import type { BehindClass } from "../../api/today";
import { shortDay } from "../../lib/planDates";

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
              {shortDay(c.earliest_missed_date)}
              <span className="text-ink-500">
                {" "}
                — starting with Chapter {c.chapter_code} · {c.chapter_title}
              </span>
            </span>
            <Link
              to={`/tutor/groups/${c.group_id}/schedule`}
              aria-label={`Review the plan for ${c.group_name}`}
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
