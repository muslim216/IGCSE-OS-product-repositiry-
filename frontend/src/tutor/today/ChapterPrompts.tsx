import { Link } from "react-router-dom";
import type { ChapterPrompt } from "../../api/today";
import NotNow from "../../components/NotNow";
import { useReportHidden, type Dismissals } from "../../lib/dismissals";

const promptKey = (p: ChapterPrompt) => `chapter_prompt:${p.group_id}:${p.chapter_id}`;

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
 * nothing else on the page changes, and each row has a "Not now" that hides it
 * (owner, 2026-10-06). The key names the class and the chapter, so a different
 * chapter coming up is a new prompt and shows. Renders nothing when there are
 * none, or none left after hiding, like every other section here (UX-29).
 */
export default function ChapterPrompts({
  prompts,
  dismissals,
}: Readonly<{
  prompts: ChapterPrompt[];
  dismissals?: Dismissals;
}>) {
  const shown = prompts.filter((p) => !dismissals?.isHidden(promptKey(p)));
  useReportHidden(
    dismissals,
    "chapter-prompts",
    prompts.filter((p) => dismissals?.isHidden(promptKey(p))).map(promptKey),
  );
  if (shown.length === 0) return null;
  return (
    <section aria-labelledby="chapter-prompts-heading">
      <h2 id="chapter-prompts-heading" className="avora-label mb-3">
        Coming up in your plan
      </h2>
      <ul className="text-sm">
        {shown.map((p) => (
          <li
            key={`${p.group_id}-${p.chapter_id}`}
            className="flex flex-wrap items-center justify-between gap-2 border-t border-line py-2.5"
          >
            <span className="text-ink-700">
              <span className="font-medium text-ink-900">{p.group_name}</span>{" "}
              {p.started ? "is on" : `starts ${shortDate(p.starts_on)}:`} Chapter {p.chapter_code} ·{" "}
              {p.chapter_title}
              <span className="text-ink-500"> — no homework for it yet</span>
            </span>
            <span className="flex items-center gap-2">
              <Link
                to={`/tutor/groups/${p.group_id}/new-homework`}
                className="font-medium text-brand-600 hover:text-brand-700"
              >
                Set homework for this chapter →
              </Link>
              {dismissals && (
                <NotNow
                  what={`${p.group_name}, Chapter ${p.chapter_code}`}
                  dismissals={dismissals}
                  hideKey={promptKey(p)}
                />
              )}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
