import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { listGroups } from "../api/groups";
import { groupAnalytics } from "../api/readiness";
import { deriveLearnerRows } from "../lib/readiness";
import ReadinessTable, { type ReadinessFilter } from "../components/ReadinessTable";
import { EmptyState } from "../components/ui";

// This page used to hand-roll its own two-card markup and a second copy of the
// >= 70 / >= 50 percentage colouring. Both are gone: a band is a grade's position
// in its boundary list, not a percentage (UX-28), and the learner table now
// renders through the shared <ReadinessTable>, exactly as the Today dashboard
// does — one component, one status source, one set of semantic tokens (UX-2).

export default function ClassReadinessPage() {
  const groups = useQuery({ queryKey: ["groups"], queryFn: listGroups });
  const [groupId, setGroupId] = useState<number | null>(null);
  const [filter, setFilter] = useState<ReadinessFilter>("all");
  const activeId = groupId ?? groups.data?.[0]?.id ?? null;
  const activeGroup = groups.data?.find((g) => g.id === activeId) ?? null;

  const analytics = useQuery({
    queryKey: ["analytics", activeId],
    queryFn: () => groupAnalytics(activeId as number),
    enabled: activeId !== null,
  });

  const rows = useMemo(
    () => (activeGroup ? deriveLearnerRows([activeGroup], [analytics.data]) : []),
    [activeGroup, analytics.data],
  );
  // The backend caps each class's weak-student list; a full class shows the
  // lowest-readiness subset, and the table says so rather than implying it is all.
  const capped = (analytics.data?.weak_students.length ?? 0) >= 10;

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

          <ReadinessTable
            rows={rows}
            filter={filter}
            onFilter={setFilter}
            loading={groups.isLoading || analytics.isLoading}
            error={analytics.isError}
            capped={capped}
          />
        </>
      )}
    </div>
  );
}
