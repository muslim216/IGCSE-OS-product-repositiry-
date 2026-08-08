import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { listGroups } from "../api/groups";
import { groupAnalytics } from "../api/readiness";

// The old >= 70 / >= 50 percentage colouring lived here as a second copy of the
// deleted statusOf(). A band is a grade's position in its boundary list, not a
// percentage (UX-28); this page's analytics rows carry only a bare score, so the
// score renders without a fabricated colour until a later stage converges this
// page onto <ReadinessTable>, which colours from the backend's band.

export default function ClassReadinessPage() {
  const groups = useQuery({ queryKey: ["groups"], queryFn: listGroups });
  const [groupId, setGroupId] = useState<number | null>(null);
  const activeId = groupId ?? groups.data?.[0]?.id ?? null;

  const analytics = useQuery({
    queryKey: ["analytics", activeId],
    queryFn: () => groupAnalytics(activeId as number),
    enabled: activeId !== null,
  });

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-xl font-semibold text-slate-800">Class readiness</h2>
        <p className="text-sm text-slate-500">
          Drill into a group's readiness, and flag students who need attention.
        </p>
      </div>

      <select
        className="rounded-md border border-slate-300 px-3 py-2 text-sm"
        value={activeId ?? ""}
        onChange={(e) => setGroupId(Number(e.target.value))}
      >
        {groups.data?.map((g) => (
          <option key={g.id} value={g.id}>
            {g.name}
          </option>
        ))}
      </select>

      {analytics.data && (
        <div className="grid gap-4 md:grid-cols-2">
          <div className="rounded-lg border bg-white p-4">
            <h3 className="font-medium text-slate-800">Students needing attention</h3>
            <ul className="mt-2 divide-y text-sm">
              {analytics.data.weak_students.map((s) => (
                <li key={s.student_id} className="flex items-center justify-between py-1.5">
                  <Link
                    to={`/tutor/students/${s.student_id}?group=${activeId}`}
                    className="text-blue-600 hover:underline"
                  >
                    {s.student_name}
                  </Link>
                  <span className="font-medium text-slate-700">{Math.round(s.score)}%</span>
                </li>
              ))}
              {analytics.data.weak_students.length === 0 && (
                <li className="py-1.5 text-slate-500">No readiness data yet.</li>
              )}
            </ul>
          </div>

          <div className="rounded-lg border bg-white p-4">
            <h3 className="font-medium text-slate-800">Weakest topics (class average)</h3>
            <ul className="mt-2 divide-y text-sm">
              {analytics.data.weak_topics.map((t) => (
                <li key={t.topic_code} className="flex items-center justify-between py-1.5">
                  <span className="text-slate-700">
                    {t.topic_code} {t.topic_title}
                  </span>
                  <span className="font-medium text-slate-700">{Math.round(t.avg_score)}%</span>
                </li>
              ))}
              {analytics.data.weak_topics.length === 0 && (
                <li className="py-1.5 text-slate-500">No readiness data yet.</li>
              )}
            </ul>
          </div>
        </div>
      )}

      {groups.data?.length === 0 && (
        <p className="text-sm text-slate-500">Create a group first to see class readiness.</p>
      )}
    </div>
  );
}
