import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, ChevronRight } from "lucide-react";
import { assignmentsNeedingAttention, reviewQueue } from "../api/homework";
import { REASON_LABELS } from "../lib/labels";
import { SectionCard } from "../components/ui";
import { Button } from "../components/controls";
import { ErrorState, PageHeader, SectionSkeleton } from "../components/page";

function SectionTitle({ title, count }: { title: string; count: number }) {
  return (
    <div className="flex items-baseline gap-3">
      <h2 className="text-lg text-ink-900">{title}</h2>
      <span className="text-sm text-ink-500">{count} waiting</span>
    </div>
  );
}

/**
 * The tutor's Review destination: everything waiting on a human decision. It
 * leads with the marking queue (AI-unsure marks and student remark requests) and
 * follows with anything else the pipeline flagged. Homework is marked
 * automatically — this is only the residue the AI wasn't sure about, so a quiet
 * queue is the healthy state and says so once, rather than showing an empty
 * card above an empty state.
 */
export default function ReviewQueuePage() {
  const queue = useQuery({ queryKey: ["review-queue"], queryFn: reviewQueue });
  const attention = useQuery({
    queryKey: ["assignments-attention"],
    queryFn: assignmentsNeedingAttention,
  });

  const queueItems = queue.data ?? [];
  // The attention list also carries submissions with marks awaiting a
  // decision — the same work the queue above already lists. Shown twice, two
  // waiting submissions read as four. This section keeps only what the queue
  // does not: failed extractions, failed marking, and the like.
  const queued = new Set(queueItems.map((q) => q.submission_id));
  const attentionItems = (attention.data ?? []).filter(
    (a) => a.submission_id == null || !queued.has(a.submission_id),
  );
  const loading = queue.isLoading || attention.isLoading;
  // "All caught up" is a claim about both lists, so it is only made when both
  // actually loaded. A failed request knows nothing about what is waiting.
  const allClear =
    !loading &&
    !queue.isError &&
    !attention.isError &&
    queueItems.length === 0 &&
    attentionItems.length === 0;

  return (
    <div>
      <PageHeader
        title="Review"
        description="Homework is marked automatically. You review only the marks the AI wasn't sure about, plus anything a learner has asked you to look at again."
      />

      <div className="space-y-6">
        {loading ? (
          <SectionCard>
            <SectionSkeleton rows={4} label="Loading your review queue" />
          </SectionCard>
        ) : queue.isError ? (
          // "Nothing to review" would be a claim; the request failed, so the
          // surface does not know what is in the queue.
          <ErrorState
            title="Your review queue didn't load"
            error={queue.error}
            onRetry={() => queue.refetch()}
          />
        ) : (
          queueItems.length > 0 && (
            <SectionCard>
              <SectionTitle title="Needs your review" count={queueItems.length} />
              <ul className="-mx-5 mt-3 divide-y divide-line border-t border-line">
                {queueItems.map((item) => (
                  <li key={item.submission_id}>
                    <Link
                      to={`/tutor/submissions/${item.submission_id}?queue=review`}
                      className="flex items-center justify-between gap-3 px-5 py-3 text-sm transition-colors hover:bg-surface-muted"
                    >
                      <span className="min-w-0">
                        <span className="flex flex-wrap items-center gap-2">
                          <span className="font-medium text-ink-900">{item.assignment_title}</span>
                          {item.past_paper_id && (
                            <span className="rounded bg-surface-muted px-1.5 py-0.5 text-xs text-ink-500">
                              Past paper
                            </span>
                          )}
                        </span>
                        <span className="text-ink-500">{item.student_name}</span>
                      </span>
                      <span className="flex shrink-0 items-center gap-2 text-xs">
                        {item.unsure_count > 0 && (
                          <span className="rounded-full bg-warn-100 px-2 py-0.5 font-medium text-warn-700">
                            {item.unsure_count} {item.unsure_count === 1 ? "mark" : "marks"} unsure
                          </span>
                        )}
                        {item.remark_request_count > 0 && (
                          <span className="rounded-full bg-remark-100 px-2 py-0.5 font-medium text-remark-600">
                            {item.remark_request_count} remark request
                            {item.remark_request_count > 1 ? "s" : ""}
                          </span>
                        )}
                        <ChevronRight aria-hidden className="h-4 w-4 text-ink-500" />
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            </SectionCard>
          )
        )}

        {attention.isError && !loading && (
          <div
            role="alert"
            className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-line bg-surface px-5 py-4 text-sm text-ink-700"
          >
            <span>Other work that needs your attention didn't load.</span>
            <Button variant="secondary" size="sm" onClick={() => attention.refetch()}>
              Try again
            </Button>
          </div>
        )}

        {attentionItems.length > 0 && (
          <SectionCard>
            <SectionTitle title="Needs your attention" count={attentionItems.length} />
            <ul className="-mx-5 mt-3 divide-y divide-line border-t border-line">
              {attentionItems.map((a, i) => (
                <li key={i}>
                  <Link
                    to={
                      a.submission_id
                        ? `/tutor/submissions/${a.submission_id}`
                        : `/tutor/assignments/${a.assignment_id}`
                    }
                    className="flex items-center justify-between gap-3 px-5 py-3 text-sm transition-colors hover:bg-surface-muted"
                  >
                    <span className="min-w-0">
                      <span className="block font-medium text-ink-900">{a.assignment_title}</span>
                      {a.student_name && <span className="text-ink-500">{a.student_name}</span>}
                    </span>
                    <span className="flex shrink-0 items-center gap-2 text-xs">
                      <span className="rounded-full bg-warn-100 px-2 py-0.5 font-medium text-warn-700">
                        {REASON_LABELS[a.reason] ?? "Needs a look"}
                      </span>
                      <ChevronRight aria-hidden className="h-4 w-4 text-ink-500" />
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          </SectionCard>
        )}

        {allClear && (
          <SectionCard className="flex flex-col items-center px-6 py-12 text-center">
            <span className="grid h-11 w-11 place-items-center rounded-full bg-ok-100 text-ok-700">
              <CheckCircle2 aria-hidden className="h-6 w-6" />
            </span>
            <h2 className="mt-4 text-xl text-ink-900">You're all caught up.</h2>
            <p className="mt-1 max-w-sm text-sm text-ink-500">
              New homework is marked as it comes in — anything the AI is unsure about will appear
              here.
            </p>
          </SectionCard>
        )}
      </div>
    </div>
  );
}
