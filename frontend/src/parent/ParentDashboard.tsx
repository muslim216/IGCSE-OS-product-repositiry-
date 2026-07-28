import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { myChildren } from "../api/groups";
import { studentReadiness } from "../api/readiness";
import { SubjectReadinessCard } from "../components/ReadinessView";
import { ReportsPanel } from "../components/ReportsPanel";
import { EmptyState } from "../ui";

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
    // No in-app action exists here — the tutor has to send the link — so this
    // explains what will appear rather than offering a button that does nothing.
    return (
      <EmptyState
        icon="👪"
        title="No children linked yet"
        description="Ask your child's tutor to send you a parent link. Once you're linked, this page shows how ready they are for each subject, which topics need work, and progress reports written in plain language."
      />
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
          <EmptyState
            className="mt-3"
            icon="📈"
            title="No progress data yet"
            description="Readiness builds up automatically as your child's homework and mock exams are marked. Nothing to do — check back after their next piece of work."
          />
        )}
      </div>

      {selected !== null && <ReportsPanel studentId={selected} audiences={["parent"]} />}
    </div>
  );
}
