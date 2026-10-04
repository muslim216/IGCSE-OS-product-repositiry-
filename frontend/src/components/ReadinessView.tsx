import { Sparkles } from "lucide-react";
import type { SubjectReadiness } from "../api/readiness";
import ReadinessFigure from "./ReadinessFigure";
import { ABSENT } from "../lib/labels";
import { VerdictLine } from "./VerdictLine";

/* A topic has no band of its own, so its bar is drawn in one neutral colour and
   the number beside it carries the meaning (UX-28). The subject's own band is
   the status badge in its verdict line and in <ReadinessFigure>, derived from
   the grade's position in the subject's boundaries, never a percentage
   cut-off. */

/** The two markers a topic row can carry, each explained once in words below
    the list — a tooltip alone is invisible on a phone or tablet. */
const ESTIMATE_BADGE = "Includes tutor's estimate";
const LOW_CONFIDENCE_BADGE = "Low confidence";

const CONFIDENCE_NOTE: Record<string, string> = {
  low: "Early estimate — more work needed to be sure",
  medium: "Fairly confident",
  high: "Confident",
  none: "Not enough data yet",
};

function Badge({ children }: { children: string }) {
  return (
    <span className="shrink-0 rounded-md bg-surface-muted px-1.5 py-0.5 text-[11px] font-medium text-ink-500">
      {children}
    </span>
  );
}

export function SubjectReadinessCard({
  subject,
  onTopicClick,
}: {
  subject: SubjectReadiness;
  onTopicClick?: (topicId: number) => void;
}) {
  const anyEstimate =
    subject.topics.some((t) => t.tutor_estimate) ||
    subject.weak_topics.some((t) => t.tutor_estimate);
  const anyLowConfidence = subject.topics.some((t) => t.confidence === "low");

  return (
    <div className="rounded-xl border border-line bg-surface p-5 shadow-[0_1px_2px_rgba(44,26,14,0.06)]">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="font-display text-lg text-ink-900">{subject.subject_name}</h3>
            {subject.is_updating && (
              <span
                className="rounded-md bg-brand-50 px-2 py-0.5 text-xs font-medium text-brand-700"
                title="New evidence has come in — this score is being recalculated."
              >
                {ABSENT.updating}
              </span>
            )}
          </div>
          <p className="text-sm text-ink-500">{subject.exam_board}</p>
          <div className="mt-1.5">
            <VerdictLine role="tutor" verdict={subject.verdict} />
          </div>
        </div>
        {subject.score !== null ? (
          // The status is the badge in the verdict line beside the name, so it
          // is not printed twice; grade and score follow the shared format.
          <div className="shrink-0 text-right">
            <ReadinessFigure
              score={subject.score}
              grade={subject.predicted_grade}
              status={null}
              boundariesMissing={subject.predicted_grade === null}
              size="lg"
            />
          </div>
        ) : (
          <span className="shrink-0 rounded-md bg-surface-muted px-2 py-1 text-xs text-ink-500">
            Not enough data yet
          </span>
        )}
      </div>

      {/* Announced, and the last known score kept on screen beneath it — a
          stale value is shown as stale, never blanked (UX-13, UX-21). */}
      <div aria-live="polite">
        {subject.is_updating && subject.score !== null && (
          <p className="mt-2 text-xs text-brand-700">
            Showing the last calculated score while a new one is worked out.
          </p>
        )}
      </div>

      {/* A fact, not a score (AV-32): shown even when there is no readiness
          score yet, because handed-in-but-unmarked homework is real evidence
          of effort the score itself can't carry. Both counts are null, not
          0, when the run has no homework evidence to count — so this line is
          simply absent rather than claiming "0 of 0" (PROD-2).
          `!= null` (loose), not `!== null`: during a Vercel-ahead-of-Render
          deploy skew the old API response omits these keys entirely, making
          them `undefined` rather than `null` — a strict check would let that
          through and render "Homework:  of  handed in". */}
      {subject.homework_assignment_count != null && subject.homework_submitted_count != null && (
        <p className="mt-3 text-sm text-ink-700">
          Homework: {subject.homework_submitted_count} of {subject.homework_assignment_count} handed
          in
        </p>
      )}

      {/* Both of these are written by the AI from the evidence (the v2
          rationale and revision plan), so they are labelled as such and set
          apart from the measured numbers above — a proposal for the tutor to
          weigh, not a finding (UX-22, PROD-7). */}
      {(subject.rationale || subject.recommended_revision) && (
        <div className="mt-4 rounded-lg border border-line bg-canvas p-3 text-sm">
          <p className="flex items-center gap-1.5 text-xs font-medium text-ink-500">
            <Sparkles aria-hidden className="h-3.5 w-3.5 text-brand-600" />
            AI summary of the evidence — check it against the topics below
          </p>
          {subject.rationale && <p className="mt-2 text-ink-700">{subject.rationale}</p>}
          {subject.recommended_revision && (
            <p className="mt-2 text-ink-700">
              <span className="font-medium text-ink-900">What to do next: </span>
              {subject.recommended_revision}
            </p>
          )}
        </div>
      )}

      {subject.weak_topics.length > 0 && (
        <div className="mt-4">
          <p className="text-sm font-medium text-ink-900">Focus on these topics</p>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {subject.weak_topics.map((t) => (
              <button
                key={t.topic_id}
                type="button"
                onClick={() => onTopicClick?.(t.topic_id)}
                className="inline-flex items-center gap-1.5 rounded-full bg-risk-100 px-2.5 py-1 text-xs text-risk-600 transition-colors hover:opacity-80"
                title={`${t.topic_code} · ${Math.round(t.score)}%`}
              >
                <span className="font-medium">{t.topic_title}</span>
                <span className="tabular-nums opacity-80">{Math.round(t.score)}%</span>
                {t.tutor_estimate && (
                  <>
                    <span aria-hidden>·</span>
                    <span>{ESTIMATE_BADGE}</span>
                  </>
                )}
              </button>
            ))}
          </div>
        </div>
      )}

      {subject.topics.length > 0 && (
        <div className="mt-4">
          <p className="text-sm font-medium text-ink-900">Topic breakdown</p>
          <ul className="mt-2 space-y-0.5">
            {subject.topics.map((t) => (
              <li key={t.topic_id}>
                <button
                  type="button"
                  onClick={() => onTopicClick?.(t.topic_id)}
                  className="grid w-full grid-cols-[minmax(0,1fr)_5rem_3rem] items-center gap-3 rounded-md px-2 py-1.5 text-left text-sm transition-colors hover:bg-surface-muted"
                  title={CONFIDENCE_NOTE[t.confidence]}
                >
                  <span className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
                    <span className="min-w-0 truncate text-ink-900">{t.topic_title}</span>
                    <span className="text-xs text-ink-500">{t.topic_code}</span>
                    {t.tutor_estimate && <Badge>{ESTIMATE_BADGE}</Badge>}
                    {t.confidence === "low" && <Badge>{LOW_CONFIDENCE_BADGE}</Badge>}
                  </span>
                  <span
                    aria-hidden
                    className="block h-1.5 overflow-hidden rounded-full bg-surface-muted"
                  >
                    <span
                      className="block h-full rounded-full bg-brand-500"
                      style={{ width: `${Math.max(0, Math.min(100, t.score))}%` }}
                    />
                  </span>
                  <span className="text-right tabular-nums text-ink-700">
                    {Math.round(t.score)}%
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {(anyEstimate || anyLowConfidence) && (
        <dl className="mt-4 space-y-1 border-t border-line pt-3 text-xs leading-relaxed text-ink-500">
          {anyEstimate && (
            <div>
              <dt className="inline font-medium text-ink-700">Tutor&apos;s estimate: </dt>
              <dd className="inline">
                part of the score is a starting level a tutor entered, not marked work. It counts
                for less as marked work comes in.
              </dd>
            </div>
          )}
          {anyLowConfidence && (
            <div>
              <dt className="inline font-medium text-ink-700">Low confidence: </dt>
              {/* "Evidence", not "marked work": a topic resting on the tutor's
                  estimate alone is low confidence with no marked work at all. */}
              <dd className="inline">only a little evidence is behind this topic so far.</dd>
            </div>
          )}
        </dl>
      )}
    </div>
  );
}
