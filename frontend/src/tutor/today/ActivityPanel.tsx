import { Link } from "react-router-dom";
import type { AssignmentAttention } from "../../api/homework";
import { EmptyState, SectionCard, SectionHeader } from "../../components/ui";
import { REASON_LABELS } from "./DashboardHeader";

export default function ActivityPanel({
  items,
  isLoading,
  isError,
}: {
  items: AssignmentAttention[] | undefined;
  isLoading: boolean;
  isError: boolean;
}) {
  const list = items ?? [];

  return (
    <SectionCard>
      <SectionHeader
        title="Needs your review"
        description="Recent work waiting on you"
        action={
          <Link to="/tutor/homework" className="font-medium text-brand-600 hover:text-brand-700">
            All homework →
          </Link>
        }
      />

      {isLoading ? (
        <div className="mt-4 space-y-3" aria-hidden>
          {[0, 1, 2].map((i) => (
            <span key={i} className="block h-8 w-full animate-pulse rounded bg-surface-muted" />
          ))}
        </div>
      ) : isError ? (
        <EmptyState
          title="Recent activity couldn't be loaded."
          hint="This is usually temporary — refresh the page to try again."
        />
      ) : list.length === 0 ? (
        <EmptyState
          title="Nothing needs review right now."
          hint="Newly marked submissions will appear here as they arrive."
        />
      ) : (
        <ul className="mt-3 divide-y divide-line">
          {list.slice(0, 5).map((item, i) => (
            <li key={i} className="py-2.5">
              <Link
                to={
                  item.submission_id
                    ? `/tutor/submissions/${item.submission_id}`
                    : `/tutor/assignments/${item.assignment_id}`
                }
                className="block text-sm font-medium text-ink-900 hover:text-brand-700"
              >
                {item.assignment_title}
                {item.student_name && (
                  <span className="font-normal text-ink-500"> — {item.student_name}</span>
                )}
              </Link>
              <span className="mt-0.5 block text-xs text-warn-700">
                {REASON_LABELS[item.reason] ?? item.reason}
              </span>
            </li>
          ))}
        </ul>
      )}
    </SectionCard>
  );
}
