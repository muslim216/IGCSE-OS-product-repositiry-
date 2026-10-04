import { Link } from "react-router-dom";
import type { ChapterPrompt } from "../../api/today";

/** "Mon 12 Oct". The plan's dates are calendar dates with no zone, so they are
    parsed as local noon-free parts rather than through `new Date(iso)`, which
    reads a bare date as UTC midnight and can print the day before. */
function shortDate(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString(undefined, {
    weekday: "short",
    day: "numeric",
    month: "short",
  });
}

/**
 * "Coming up in your plan": chapters from an accepted plan that have begun, or
 * begin within the week, with no classified uploaded (AV-20, AV-22).
 *
 * Information with a link, never a gate — a tutor can ignore every row and
 * nothing else on the page changes. Renders nothing when there are none, like
 * every other section on this page (UX-29).
 */
export default function ChapterPrompts({ prompts }: { prompts: ChapterPrompt[] }) {
  if (prompts.length === 0) return null;
  return (
    <section aria-labelledby="chapter-prompts-heading">
      <h2 id="chapter-prompts-heading" className="avora-label mb-3">
        Coming up in your plan
      </h2>
      <ul className="text-sm">
        {prompts.map((p) => (
          <li
            key={`${p.group_id}-${p.chapter_id}`}
            className="flex flex-wrap items-center justify-between gap-2 border-t border-line py-2.5"
          >
            <span className="text-ink-700">
              <span className="font-medium text-ink-900">{p.group_name}</span>{" "}
              {p.started ? "is on" : `starts ${shortDate(p.starts_on)}:`} Chapter {p.chapter_code} ·{" "}
              {p.chapter_title}
              <span className="text-ink-500"> — no classified uploaded yet</span>
            </span>
            <Link
              to={`/tutor/groups/${p.group_id}/new-homework`}
              className="font-medium text-brand-600 hover:text-brand-700"
            >
              Set homework for this chapter →
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
