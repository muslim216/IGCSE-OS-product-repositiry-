import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { listGroups } from "../api/groups";
import { classOverview } from "../api/today";
import type { LearnerRow } from "../lib/readiness";
import ReadinessTable, { type ReadinessFilter } from "../components/ReadinessTable";
import { EmptyState } from "../components/ui";
import { ABSENT } from "../lib/labels";

/**
 * Class readiness, rendered through the shared <ReadinessTable>.
 *
 * The rows come from /today/classes/{id}, NOT from groupAnalytics via
 * deriveLearnerRows(). That distinction is the whole point of this page: the
 * analytics feed carries only a bare score, so deriving a status from it means
 * falling back to the legacy 70/50 percentage cutoffs — and a band is a grade's
 * position in its boundary list, never a percentage (UX-28). The class-overview
 * endpoint bands each learner from the organization's own grade boundaries, so
 * the colour here is the same claim the rest of the product makes.
 *
 * A subject with no boundaries therefore has no band, and this page says so
 * rather than colouring learners against a threshold it does not have (PROD-2).
 */
export default function ClassReadinessPage() {
  const groups = useQuery({ queryKey: ["groups"], queryFn: listGroups });
  const [groupId, setGroupId] = useState<number | null>(null);
  const [filter, setFilter] = useState<ReadinessFilter>("all");
  const activeId = groupId ?? groups.data?.[0]?.id ?? null;

  const overview = useQuery({
    queryKey: ["class-overview", activeId],
    queryFn: () => classOverview(activeId as number),
    enabled: activeId !== null,
  });

  const rows = useMemo<LearnerRow[]>(() => {
    const data = overview.data;
    if (!data) return [];
    return data.learners.flatMap((l) =>
      // A learner with no score or no band is absent rather than fabricated:
      // the table colours by band, and there is no honest colour without one.
      l.score === null || l.status === null
        ? []
        : [
            {
              student_id: l.student_id,
              student_name: l.student_name,
              subject_name: data.subject_name,
              score: l.score,
              status: l.status,
              group_id: data.group_id,
              group_name: data.name,
            },
          ],
    );
  }, [overview.data]);

  return (
    <div className="space-y-4">
      <div>
        <h2 className="font-display text-xl font-semibold text-ink-900">Class readiness</h2>
        <p className="text-sm text-ink-500">
          Drill into a class's readiness, and flag learners who need attention.
        </p>
      </div>

      {groups.data && groups.data.length === 0 ? (
        <EmptyState
          title="You haven't set up a class yet."
          hint="Create a class and share its code — readiness appears once learners join and work is marked."
        />
      ) : (
        <>
          {groups.data && groups.data.length > 1 && (
            <label className="block text-sm">
              <span className="sr-only">Choose a class</span>
              <select
                className="rounded-md border border-line bg-surface px-3 py-2 text-sm text-ink-900"
                value={activeId ?? ""}
                onChange={(e) => setGroupId(Number(e.target.value))}
              >
                {groups.data.map((g) => (
                  <option key={g.id} value={g.id}>
                    {g.name}
                  </option>
                ))}
              </select>
            </label>
          )}

          {overview.data?.boundaries_missing ? (
            <EmptyState
              title={ABSENT.noBoundaries}
              hint="Readiness needs this subject's grade boundaries before it can band a learner."
              action={
                <Link
                  to="/tutor/library"
                  className="font-medium text-brand-600 hover:text-brand-700"
                >
                  {ABSENT.noBoundariesAction}
                </Link>
              }
            />
          ) : (
            <ReadinessTable
              rows={rows}
              filter={filter}
              onFilter={setFilter}
              loading={groups.isLoading || overview.isLoading}
              error={overview.isError}
            />
          )}
        </>
      )}
    </div>
  );
}
