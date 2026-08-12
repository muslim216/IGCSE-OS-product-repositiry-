import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { assignmentsNeedingAttention, reviewQueue } from "../api/homework";
import { ABSENT, REASON_LABELS } from "../lib/labels";
import { EmptyState } from "../components/ui";

/**
 * The tutor's Review destination: everything waiting on a human decision. It
 * leads with the marking queue (AI-unsure marks and student remark requests) and
 * follows with anything else the pipeline flagged. Homework is marked
 * automatically — this is only the residue the AI wasn't sure about, so a quiet
 * queue is the healthy state and says so rather than showing an empty card.
 */
export default function ReviewQueuePage() {
  const queue = useQuery({ queryKey: ["review-queue"], queryFn: reviewQueue });
  const attention = useQuery({
    queryKey: ["assignments-attention"],
    queryFn: assignmentsNeedingAttention,
  });

  const queueItems = queue.data ?? [];
  const attentionItems = attention.data ?? [];

  return (
    <div className="space-y-6">
      <div>
        <h2 className="font-display text-xl font-semibold text-ink-900">Review</h2>
        <p className="text-sm text-ink-500">
          Homework is marked automatically. You review only the marks the AI wasn't sure about, plus
          anything a learner has asked you to look at again.
        </p>
      </div>

      <section className="rounded-lg border border-line bg-surface p-4">
        <div className="flex items-center gap-2">
          <h3 className="font-medium text-ink-900">Needs your review</h3>
          {queueItems.length > 0 && (
            <span className="rounded-full bg-warn-100 px-2 py-0.5 text-xs font-medium text-warn-700">
              {queueItems.length}
            </span>
          )}
        </div>
        {queue.isLoading ? (
          <p className="mt-2 text-sm text-ink-500">Loading…</p>
        ) : queue.isError ? (
          // "Nothing to review" would be a claim; the request failed, so the
          // surface does not know what is in the queue.
          <p className="mt-2 text-sm text-ink-500">{ABSENT.loadFailed}</p>
        ) : queueItems.length === 0 ? (
          <p className="mt-2 text-sm text-ink-500">
            Nothing to review — everything was marked confidently.
          </p>
        ) : (
          <ul className="mt-2 divide-y divide-line text-sm">
            {queueItems.map((item) => (
              <li key={item.submission_id} className="flex items-center justify-between gap-3 py-2">
                <div className="min-w-0">
                  <Link
                    to={`/tutor/submissions/${item.submission_id}?queue=review`}
                    className="font-medium text-brand-600 hover:text-brand-700"
                  >
                    {item.assignment_title}
                  </Link>
                  {item.past_paper_id && (
                    <span className="ml-2 rounded bg-surface-muted px-1.5 py-0.5 text-xs text-ink-500">
                      Past paper
                    </span>
                  )}
                  <span className="ml-2 text-ink-500">— {item.student_name}</span>
                </div>
                <div className="flex shrink-0 gap-2 text-xs">
                  {item.unsure_count > 0 && (
                    <span className="rounded bg-warn-100 px-2 py-0.5 text-warn-700">
                      {item.unsure_count} unsure
                    </span>
                  )}
                  {item.remark_request_count > 0 && (
                    <span className="rounded bg-remark-100 px-2 py-0.5 text-remark-600">
                      {item.remark_request_count} remark request
                      {item.remark_request_count > 1 ? "s" : ""}
                    </span>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      {attentionItems.length > 0 && (
        <section className="rounded-lg border border-line bg-surface p-4">
          <h3 className="font-medium text-ink-900">Needs your attention</h3>
          <ul className="mt-2 divide-y divide-line text-sm">
            {attentionItems.map((a, i) => (
              <li key={i} className="flex items-center justify-between gap-3 py-2">
                <div className="min-w-0">
                  <Link
                    to={
                      a.submission_id
                        ? `/tutor/submissions/${a.submission_id}`
                        : `/tutor/assignments/${a.assignment_id}`
                    }
                    className="font-medium text-brand-600 hover:text-brand-700"
                  >
                    {a.assignment_title}
                  </Link>
                  {a.student_name && <span className="ml-2 text-ink-500">— {a.student_name}</span>}
                </div>
                <span className="shrink-0 text-warn-700">
                  {REASON_LABELS[a.reason] ?? a.reason}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {!queue.isLoading &&
        !queue.isError &&
        queueItems.length === 0 &&
        attentionItems.length === 0 &&
        !attention.isLoading && (
          <EmptyState
            title="You're all caught up."
            hint="New homework is marked as it comes in — anything the AI is unsure about will appear here."
          />
        )}
    </div>
  );
}
