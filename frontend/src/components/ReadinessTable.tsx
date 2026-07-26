import { Link } from "react-router-dom";
import type { LearnerRow } from "../lib/readiness";
import { EmptyState, InitialsAvatar, ReadinessBar, StatusBadge } from "./ui";

export type ReadinessFilter = "all" | "needs_attention" | "on_track";

const TABS: { id: ReadinessFilter; label: string }[] = [
  { id: "all", label: "All" },
  { id: "needs_attention", label: "Needs attention" },
  { id: "on_track", label: "On track" },
];

export function matchesFilter(row: LearnerRow, filter: ReadinessFilter): boolean {
  if (filter === "all") return true;
  if (filter === "on_track") return row.status === "on_track";
  return row.status !== "on_track";
}

function SkeletonRows() {
  return (
    <>
      {[0, 1, 2].map((i) => (
        <tr key={i} className="border-t border-line">
          <td colSpan={5} className="px-2 py-3">
            <span aria-hidden className="block h-4 w-full animate-pulse rounded bg-surface-muted" />
          </td>
        </tr>
      ))}
    </>
  );
}

/**
 * Learner evidence table. Everything arrives via props so the same table can
 * serve the dashboard, a class view, or a future organization-wide roster.
 * Learners without marked evidence are simply absent — never shown as a zero.
 */
export default function ReadinessTable({
  rows,
  filter,
  onFilter,
  searchQuery = "",
  loading = false,
  error = false,
  capped = false,
}: {
  rows: LearnerRow[];
  filter: ReadinessFilter;
  onFilter: (filter: ReadinessFilter) => void;
  searchQuery?: string;
  loading?: boolean;
  error?: boolean;
  /** A class hit the server's per-class limit, so the list is the lowest-scoring subset. */
  capped?: boolean;
}) {
  const flagged = rows.filter((r) => r.status !== "on_track").length;
  const query = searchQuery.trim().toLowerCase();
  const visible = rows.filter(
    (r) => matchesFilter(r, filter) && (!query || r.student_name.toLowerCase().includes(query)),
  );

  const counts: Record<ReadinessFilter, number> = {
    all: rows.length,
    needs_attention: flagged,
    on_track: rows.length - flagged,
  };

  return (
    <div>
      {rows.length > 0 && (
        <p className="text-sm text-ink-700">
          {flagged > 0 ? (
            <>
              <span className="font-semibold text-warn-700">
                {flagged} learner{flagged === 1 ? "" : "s"}
              </span>{" "}
              may need support before their next assessment.
            </>
          ) : (
            <>Everyone with readiness evidence is currently on track.</>
          )}
        </p>
      )}

      {rows.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-5 border-b border-line">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              type="button"
              aria-pressed={filter === tab.id}
              onClick={() => onFilter(tab.id)}
              className={`-mb-px border-b-2 pb-2 text-xs font-medium transition ${
                filter === tab.id
                  ? "border-brand-600 text-ink-900"
                  : "border-transparent text-ink-500 hover:text-ink-900"
              }`}
            >
              {tab.label}
              <span className="ml-1.5 tabular-nums opacity-70">{counts[tab.id]}</span>
            </button>
          ))}
        </div>
      )}

      {error && rows.length === 0 ? (
        <EmptyState
          title="Readiness evidence couldn't be loaded."
          hint="This is usually temporary — refresh the page to try again."
        />
      ) : loading && rows.length === 0 ? (
        <table className="mt-3 w-full">
          <caption className="sr-only">Loading learner readiness</caption>
          <tbody>
            <SkeletonRows />
          </tbody>
        </table>
      ) : rows.length === 0 ? (
        <EmptyState
          title="No readiness evidence yet."
          hint="Marked homework, assessments and past papers build each learner's picture."
          action={
            <Link to="/tutor/homework" className="font-medium text-brand-600 hover:text-brand-500">
              Go to homework →
            </Link>
          }
        />
      ) : (
        <div className="mt-3 overflow-x-auto">
          <table className="w-full text-left text-sm">
            <caption className="sr-only">Learner readiness, lowest first</caption>
            <thead>
              <tr className="text-xs uppercase tracking-wide text-ink-400">
                <th scope="col" className="py-2 pr-3 font-medium">Learner</th>
                <th scope="col" className="py-2 pr-3 font-medium">Subject</th>
                <th scope="col" className="py-2 pr-3 font-medium">Readiness</th>
                <th scope="col" className="py-2 pr-3 font-medium">Status</th>
                <th scope="col" className="py-2 font-medium">Next step</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((row) => (
                <tr key={`${row.student_id}:${row.subject_name}`} className="border-t border-line">
                  <th scope="row" className="py-3 pr-3 font-normal">
                    <span className="flex items-center gap-2.5">
                      <InitialsAvatar name={row.student_name} size="sm" />
                      <span className="font-medium text-ink-900">{row.student_name}</span>
                    </span>
                  </th>
                  <td className="py-3 pr-3 text-ink-500">{row.subject_name}</td>
                  <td className="py-3 pr-3">
                    <span className="flex items-center gap-2">
                      <span className="w-9 shrink-0 font-display text-[15px] tabular-nums text-ink-900">
                        {Math.round(row.score)}%
                      </span>
                      <ReadinessBar score={row.score} status={row.status} />
                    </span>
                  </td>
                  <td className="py-3 pr-3">
                    <StatusBadge status={row.status} />
                  </td>
                  <td className="py-3">
                    <Link
                      to={`/tutor/students/${row.student_id}`}
                      className="font-medium text-brand-600 hover:text-brand-500"
                    >
                      Review evidence →
                    </Link>
                  </td>
                </tr>
              ))}
              {visible.length === 0 && (
                <tr className="border-t border-line">
                  <td colSpan={5} className="py-6 text-center text-sm text-ink-500">
                    No learners match this view.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {rows.length > 0 && (
        <p className="mt-3 text-xs text-ink-400">
          {capped && "Showing the lowest-readiness learners per class. "}
          Learners without marked evidence aren't scored yet.
        </p>
      )}
    </div>
  );
}
