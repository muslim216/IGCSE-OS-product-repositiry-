import { useQuery } from "@tanstack/react-query";
import { myImprovement, type ImprovementPeriod, type SubjectImprovement } from "../api/improvement";
import { EmptyState } from "../components/ui";
import { ABSENT } from "../lib/labels";

/**
 * Improvement — the reader's own position, on a surface dedicated to it.
 *
 * **Nothing on this page belongs to anyone else.** No classmate row, no
 * classmate delta exact or banded, no "← you" marker inside a list of other
 * people, no names, no initials, no avatars. The ranking exists; the ranked do
 * not appear. The response carries the reader's rank, the reader's delta and a
 * count — the reasoning is in backend/app/services/improvement.py and is worth
 * reading before changing anything here.
 *
 * **It ranks improvement, not attainment.** An attainment ranking has one
 * winner and eleven losers, the order barely moves across a year, and the
 * student at the bottom in September is the student at the bottom in May. An
 * improvement ranking resets every window and can be won by anyone — including,
 * and especially, the weakest student in the room.
 *
 * **It appears on no home surface**, student or tutor. A standing a student
 * meets every day becomes a standing whose disappearance is the message.
 */

function ordinal(n: number): string {
  const rem100 = n % 100;
  if (rem100 >= 11 && rem100 <= 13) return `${n}th`;
  return `${n}${["th", "st", "nd", "rd"][n % 10] ?? "th"}`;
}

/** The reader's own movement, in words. Never rendered as a bare signed number
    with no subject — "+6" alone does not say what moved or over what. */
function deltaLabel(delta: number | null): string | null {
  if (delta === null) return null;
  const rounded = Math.round(delta);
  if (rounded === 0) return "no change";
  return rounded > 0 ? `▲ +${rounded}` : `▼ ${rounded}`;
}

/**
 * A placing, or the band that replaces it.
 *
 * A bare bottom placing is never rendered. "9th of 11" discourages even with
 * nobody named, which is the exact failure the student surfaces are designed
 * against — so below the halfway line the page says which half, and leans on
 * the reader's own movement, which is the part they can act on.
 */
function placingLine(period: ImprovementPeriod): string | null {
  if (period.rank === null) return null;
  if (period.banded)
    return `You're in the second half of your class ${period.label.toLowerCase()}.`;
  return `You're ${ordinal(period.rank)} of ${period.ranked_count} ${period.label.toLowerCase()}.`;
}

function SubjectPanel({ subject }: { subject: SubjectImprovement }) {
  const [current, ...history] = subject.periods;
  const placing = current ? placingLine(current) : null;
  const movement = current ? deltaLabel(current.delta) : null;

  return (
    <section className="space-y-3">
      <h3 className="avora-label">{subject.subject_name}</h3>

      {placing ? (
        <p className="font-display text-xl text-ink-900">{placing}</p>
      ) : (
        // A gate not met is a stated absence, never an empty board or a zero.
        // The reader's own movement below is a complete surface on its own.
        <p className="text-sm text-ink-500">
          Not enough of your class has a full {subject.window_days} days of marked work to compare
          yet.
        </p>
      )}

      {movement ? (
        <p className="text-sm text-ink-700">
          <span className="tabular-nums">{movement}</span> over the last {subject.window_days} days.
        </p>
      ) : (
        <p className="text-sm text-ink-500">{ABSENT.noEvidence}</p>
      )}

      {history.length > 0 && (
        <div>
          <h4 className="avora-label mb-1">Your months</h4>
          <ul className="text-sm">
            {history.map((period) => (
              <li
                key={period.label}
                className="flex flex-wrap items-center justify-between gap-2 border-t border-line py-1.5"
              >
                <span className="text-ink-700">{period.label}</span>
                <span className="tabular-nums text-ink-500">
                  {period.rank === null
                    ? "not compared"
                    : period.banded
                      ? "second half"
                      : ordinal(period.rank)}
                  {deltaLabel(period.delta) && <> · {deltaLabel(period.delta)}</>}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {subject.focus.length > 0 && (
        <div>
          <h4 className="avora-label mb-1">What would move you up</h4>
          <ul className="text-sm">
            {subject.focus.map((t) => (
              <li
                key={t.topic_code}
                className="flex flex-wrap items-center justify-between gap-2 border-t border-line py-1.5"
              >
                <span className="text-ink-700">
                  {t.topic_code} {t.topic_title}
                </span>
                <span className="tabular-nums text-ink-500">
                  {t.score === null ? ABSENT.noEvidence : `${Math.round(t.score)}%`}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

export default function ImprovementPage() {
  const improvement = useQuery({ queryKey: ["my-improvement"], queryFn: myImprovement });

  if (improvement.isLoading) {
    return (
      <div aria-busy="true">
        <span aria-hidden className="block h-32 w-full animate-pulse rounded bg-surface-muted" />
      </div>
    );
  }
  if (improvement.isError || !improvement.data) {
    return <EmptyState title="Improvement couldn't be loaded." hint={ABSENT.loadFailed} />;
  }
  if (improvement.data.length === 0) {
    return (
      <EmptyState
        title="Nothing to compare yet."
        hint="This fills in once your work has been marked for a few weeks."
      />
    );
  }

  return (
    <div className="space-y-8">
      <p className="max-w-prose text-sm text-ink-500">
        How much you've improved, compared with your class. It measures movement, not marks — so it
        resets every month and anyone can come top.
      </p>
      {improvement.data.map((s) => (
        <SubjectPanel key={s.subject_id} subject={s} />
      ))}
    </div>
  );
}
