import { useQuery } from "@tanstack/react-query";
import { myChildren } from "../api/groups";

export default function ParentDashboard() {
  const children = useQuery({ queryKey: ["my-children"], queryFn: myChildren });

  return (
    <div>
      <h2 className="text-xl font-semibold text-slate-800">Your children</h2>
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        {children.data?.map((c) => (
          <div key={c.id} className="rounded-lg border bg-white p-4">
            <div className="font-medium text-slate-800">{c.name}</div>
            <div className="mt-2 text-sm text-slate-400">
              Progress and reports coming soon
            </div>
          </div>
        ))}
        {children.data?.length === 0 && (
          <p className="text-slate-500">
            No children linked yet. Ask the tutor for a parent link.
          </p>
        )}
      </div>
    </div>
  );
}
