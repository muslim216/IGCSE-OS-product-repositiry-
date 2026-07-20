import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { myChildren } from "../api/groups";
import { studentReadiness } from "../api/readiness";
import { SubjectReadinessCard } from "../components/ReadinessView";
import { ReportsPanel } from "../components/ReportsPanel";

export default function ParentDashboard() {
  const children = useQuery({ queryKey: ["my-children"], queryFn: myChildren });
  const [activeChild, setActiveChild] = useState<number | null>(null);

  const selected = activeChild ?? children.data?.[0]?.id ?? null;

  const readiness = useQuery({
    queryKey: ["child-readiness", selected],
    queryFn: () => studentReadiness(selected!),
    enabled: selected !== null,
  });

  if (children.isLoading) return <p className="text-slate-500">Loading…</p>;
  if (children.data?.length === 0) {
    return (
      <p className="text-slate-500">
        No children linked yet. Ask the tutor for a parent link.
      </p>
    );
  }

  return (
    <div className="space-y-6">
      {children.data && children.data.length > 1 && (
        <div className="flex gap-2">
          {children.data.map((c) => (
            <button
              key={c.id}
              onClick={() => setActiveChild(c.id)}
              className={`rounded-full px-4 py-1.5 text-sm ${
                selected === c.id
                  ? "bg-blue-600 text-white"
                  : "bg-slate-100 text-slate-600 hover:bg-slate-200"
              }`}
            >
              {c.name}
            </button>
          ))}
        </div>
      )}

      <div>
        <h2 className="text-xl font-semibold text-slate-800">
          {readiness.data?.student_name}'s progress
        </h2>
        <p className="text-sm text-slate-500">
          A simple view of how your child is doing. Predicted grades are estimates
          based on their homework, mocks and their tutor's observations.
        </p>
        {readiness.data && readiness.data.subjects.length > 0 ? (
          <div className="mt-3 grid gap-4 lg:grid-cols-2">
            {readiness.data.subjects.map((s) => (
              <SubjectReadinessCard key={s.subject_id} subject={s} />
            ))}
          </div>
        ) : (
          <p className="mt-3 text-slate-500">
            No progress data yet — it builds up as homework and mocks are marked.
          </p>
        )}
      </div>

      {selected !== null && (
        <ReportsPanel studentId={selected} audiences={["parent"]} canGenerate={false} />
      )}
    </div>
  );
}
