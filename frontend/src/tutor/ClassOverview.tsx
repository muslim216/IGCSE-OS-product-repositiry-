import { Link } from "react-router-dom";
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { classOverview, type ClassLearnerRow } from "../api/today";
import { generateClassBrief } from "../api/groups";
import { groupNarrative } from "../api/narrative";
import { StatusBadge } from "../components/ui";
import { ABSENT } from "../lib/labels";
import { coverageLabel } from "../lib/verdict";

/**
 * The class page's headline: verdict → WHY → NEEDS YOU, then the roster.
 *
 * NEEDS YOU is selected on **direction, not level**. A learner sliding from a
 * grade 8 to a 6 appears; a learner who has been a stable grade 4 all year does
 * not — they are why the class carries its status, and they are still right
 * there under Learners. Nothing is hidden, it is ordered by what the tutor can
 * act on.
 */

/** No arrow at all when direction is null: one readiness point is not a trend,
    and "→" would be a claim the data does not support (UX-31, PROD-2). */
function DirectionMark({ direction }: { direction: ClassLearnerRow["direction"] }) {
  if (direction === null) return null;
  const glyph = direction === "up" ? "↑" : direction === "down" ? "↓" : "→";
  const tone =
    direction === "up" ? "text-ok-700" : direction === "down" ? "text-risk-600" : "text-ink-500";
  return (
    <span className={tone} aria-label={`Trending ${direction}`}>
      {glyph}
    </span>
  );
}

function LearnerRow({ row }: { row: ClassLearnerRow }) {
  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-line py-2.5">
      <Link
        to={`/tutor/students/${row.student_id}`}
        className="font-medium text-ink-900 hover:text-brand-600"
      >
        {row.student_name}
      </Link>
      {row.predicted_grade && (
        <span className="font-display text-[15px] tabular-nums text-ink-900">
          {row.predicted_grade}
        </span>
      )}
      <DirectionMark direction={row.direction} />
      {row.status ? (
        <StatusBadge status={row.status} />
      ) : (
        <span className="text-sm text-ink-500">{ABSENT.noEvidence}</span>
      )}
    </li>
  );
}

/** How often to re-ask whether the regenerated narrative has landed. */
const NARRATIVE_POLL_MS = 4000;
/** And how long to keep asking before accepting that it is not coming. */
const NARRATIVE_POLL_TIMEOUT_MS = 60_000;

export default function ClassOverviewPanel({ groupId }: { groupId: number }) {
  const queryClient = useQueryClient();
  // The regenerated text is written by a background job, so the POST returning
  // is not the text being ready. Invalidating once would refetch the *old* row
  // and look like the button did nothing. This holds the generated_at that was
  // on screen when "Prepare again" was pressed; the narrative query polls until
  // the stored row moves past it.
  const [awaitedSince, setAwaitedSince] = useState<string | null>(null);

  const overview = useQuery({
    queryKey: ["class-overview", groupId],
    queryFn: () => classOverview(groupId),
  });
  const narrative = useQuery({
    queryKey: ["narrative", "group", groupId],
    queryFn: () => groupNarrative(groupId),
    // While a regenerate is in flight the stored row has not changed yet; keep
    // asking until it does, then stop. The previous text stays on screen
    // throughout, marked "Updating…" (UX-21).
    refetchInterval: (query) =>
      awaitedSince !== null && (query.state.data?.generated_at ?? "") === awaitedSince
        ? NARRATIVE_POLL_MS
        : false,
  });

  // Stop polling once the new row lands.
  useEffect(() => {
    if (awaitedSince !== null && (narrative.data?.generated_at ?? "") !== awaitedSince) {
      setAwaitedSince(null);
    }
  }, [awaitedSince, narrative.data?.generated_at]);

  // And stop regardless once the wait is up. The row only moves if the job runs
  // and succeeds; if it failed, or the worker never picked it up, nothing will
  // ever change the condition above — so an unbounded poll would keep asking
  // every few seconds for as long as the tutor leaves the page open, with
  // "Updating…" pinned on screen claiming work is in progress that has stopped.
  useEffect(() => {
    if (awaitedSince === null) return;
    const timer = setTimeout(() => setAwaitedSince(null), NARRATIVE_POLL_TIMEOUT_MS);
    return () => clearTimeout(timer);
  }, [awaitedSince]);

  // "Prepare again" is D2's correction, not an approval step: a tutor who reads
  // something wrong regenerates it. No review state, no badge, no queue, and
  // nothing here implies anything is expected of them.
  const prepare = useMutation({
    mutationFn: () => generateClassBrief(groupId),
    onSuccess: () => {
      setAwaitedSince(narrative.data?.generated_at ?? "");
      queryClient.invalidateQueries({ queryKey: ["narrative", "group", groupId] });
    },
  });

  if (overview.isLoading) {
    return (
      <span aria-hidden className="block h-20 w-full animate-pulse rounded bg-surface-muted" />
    );
  }
  // A failed load is stated, not rendered as nothing: an empty region here reads
  // as a class with no data, which is a different and wrong claim (PROD-2).
  // Same treatment ClassNarrative and TodayDashboard give the same condition.
  if (overview.isError || !overview.data) {
    return (
      <section className="rounded-lg border border-line bg-surface p-4">
        <p className="text-sm text-ink-500">{ABSENT.loadFailed}</p>
      </section>
    );
  }

  const c = overview.data;
  const coverage = coverageLabel(c);

  // A class nobody has joined gets the empty-room treatment rather than a
  // dashboard of honest absences, which reads as broken rather than new.
  if (c.member_count === 0) {
    return (
      <section className="rounded-lg border border-line bg-surface p-4">
        <p className="text-sm text-ink-700">
          No learners have joined {c.name} yet. Share the class code — readiness appears once they
          join and their work is marked.
        </p>
      </section>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        {c.status ? (
          <>
            <span className="font-display text-2xl font-semibold text-ink-900">
              {c.predicted_grade}
            </span>
            <StatusBadge status={c.status} />
          </>
        ) : c.boundaries_missing ? (
          <span className="text-sm text-ink-500">
            {ABSENT.noBoundaries}{" "}
            <Link to="/tutor/library" className="font-medium text-brand-600 hover:text-brand-700">
              {ABSENT.noBoundariesAction}
            </Link>
          </span>
        ) : (
          <span className="text-sm text-ink-500">{ABSENT.noEvidence}</span>
        )}
        {coverage && (
          <span className="text-xs tabular-nums text-ink-500">
            {coverage} learners with evidence
          </span>
        )}
      </div>

      {c.weak_topics.length > 0 && (
        <section>
          <h3 className="avora-label mb-2">Why</h3>
          <ul className="text-sm">
            {c.weak_topics.map((t) => (
              <li
                key={t.topic_code}
                className="flex items-center justify-between border-t border-line py-2"
              >
                <span className="text-ink-700">
                  {t.topic_code} {t.topic_title}
                </span>
                <span className="tabular-nums text-ink-500">
                  {Math.round(t.avg_score)}% · {t.student_count}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {c.needs_you.length > 0 && (
        <section>
          <h3 className="avora-label mb-2">Needs you</h3>
          <p className="mb-1 text-sm text-ink-500">
            {c.needs_you.length === 1
              ? "One learner has declined recently."
              : `${c.needs_you.length} learners have declined recently.`}
          </p>
          <ul>
            {c.needs_you.map((row) => (
              <LearnerRow key={row.student_id} row={row} />
            ))}
          </ul>
        </section>
      )}

      {c.learners.length > 0 && (
        <section>
          <h3 className="avora-label mb-2">Learners</h3>
          <ul>
            {c.learners.map((row) => (
              <LearnerRow key={row.student_id} row={row} />
            ))}
          </ul>
        </section>
      )}

      {/* Read-only, below the fold, and only where the tutor already chose to
          look. Never pushed at them: a paragraph waiting to be read is a task,
          and this deliberately is not one (D2).

          This is the CLASS narrative (audience tutor_class) — the tutor's own
          paragraph. It was briefly labelled "What the parents see", which was
          simply untrue: the parent paragraph is a different audience with
          different rules (aggregates only, no gendered pronoun) and is stored
          per student, not per class. Surfacing the real per-child parent text
          to the tutor belongs with the parent screen (PR 25); mislabelling this
          one as parent-facing told the tutor they had checked something they
          had not. */}
      <section className="border-t border-line pt-4">
        <h3 className="avora-label mb-2">Class summary</h3>
        {narrative.data?.text ? (
          <p className="max-w-prose text-sm leading-relaxed text-ink-700">
            {narrative.data.text}
            {(narrative.isFetching || awaitedSince !== null) && (
              <span className="ml-2 text-xs text-ink-500" aria-live="polite">
                {ABSENT.updating}
              </span>
            )}
          </p>
        ) : narrative.isError ? (
          <p className="text-sm text-ink-500">{ABSENT.loadFailed}</p>
        ) : (
          <p className="text-sm text-ink-500">
            Nothing written yet — a summary appears once work is marked.
          </p>
        )}
        <button
          type="button"
          onClick={() => prepare.mutate()}
          disabled={prepare.isPending}
          className="mt-2 text-sm font-medium text-brand-600 hover:text-brand-700 disabled:opacity-60"
        >
          {prepare.isPending ? "Preparing…" : "Prepare again"}
        </button>
        {prepare.isError && <p className="mt-1 text-sm text-ink-500">{ABSENT.aiUnavailable}</p>}
      </section>
    </div>
  );
}
