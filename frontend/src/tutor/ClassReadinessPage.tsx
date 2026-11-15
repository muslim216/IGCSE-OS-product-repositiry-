import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getGroup } from "../api/groups";
import { classOverview } from "../api/today";
import { bandOf, type LearnerRow } from "../lib/readiness";
import ReadinessTable, { type ReadinessFilter } from "../components/ReadinessTable";

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
 * It renders inside a class's Progress tab, so the class is known and there is
 * no class picker.
 *
 * A subject with no boundaries therefore has no band: its learners stay in the
 * table with their score, uncoloured, and the table says why (PROD-2).
 */
export default function ClassReadinessPage({ groupId }: { groupId: number }) {
  // Same key as the class layout's own query, so this is a cache hit.
  const group = useQuery({ queryKey: ["group", groupId], queryFn: () => getGroup(groupId) });
  const [filter, setFilter] = useState<ReadinessFilter>("all");

  const overview = useQuery({
    queryKey: ["class-overview", groupId],
    queryFn: () => classOverview(groupId),
  });

  const rows = useMemo<LearnerRow[]>(() => {
    const data = overview.data;
    if (!data) return [];
    return data.learners.flatMap((l) =>
      // A learner with no score or no band is absent rather than fabricated:
      // the table colours by band, and there is no honest colour without one.
      // No score means nothing to show. A score with no status (no grade
      // boundaries, or too little to band) stays: the figure prints the score
      // alone and the table says why there is no status, rather than the
      // learner vanishing into "No readiness evidence yet".
      l.score === null || l.score === undefined
        ? []
        : [
            {
              student_id: l.student_id,
              student_name: l.student_name,
              subject_name: data.subject_name,
              score: l.score,
              predicted_grade: l.predicted_grade,
              status: bandOf(l.verdict.status),
              group_id: data.group_id,
              group_name: data.name,
            },
          ],
    );
  }, [overview.data]);

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg text-ink-900">Class readiness</h2>
        <p className="mt-0.5 text-sm text-ink-500">
          How ready each learner in this class is for the exam, and who needs attention.
        </p>
      </div>
      <ReadinessTable
        rows={rows}
        filter={filter}
        onFilter={setFilter}
        loading={overview.isLoading}
        error={overview.isError}
        boundariesMissing={overview.data?.boundaries_missing ?? false}
        subjectId={group.data?.subject.id}
      />
    </div>
  );
}
