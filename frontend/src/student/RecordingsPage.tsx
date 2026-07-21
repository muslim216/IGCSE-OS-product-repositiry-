import { useQueries, useQuery } from "@tanstack/react-query";
import { myGroups } from "../api/groups";
import { listResources } from "../api/resources";

export default function RecordingsPage() {
  const groups = useQuery({ queryKey: ["my-groups"], queryFn: myGroups });
  const resourceQueries = useQueries({
    queries: (groups.data ?? []).map((g) => ({
      queryKey: ["resources", g.id, "recording"],
      queryFn: () => listResources(g.id, "recording"),
      enabled: groups.data !== undefined,
    })),
  });

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-xl font-semibold text-slate-800">Recordings</h2>
        <p className="text-sm text-slate-500">Lesson recordings your tutors have shared.</p>
      </div>

      <div className="space-y-4">
        {(groups.data ?? []).map((g, i) => {
          const recordings = resourceQueries[i]?.data ?? [];
          if (recordings.length === 0) return null;
          return (
            <div key={g.id} className="rounded-lg border bg-white p-4">
              <h3 className="font-medium text-slate-800">{g.name}</h3>
              <ul className="mt-2 divide-y text-sm">
                {recordings.map((r) => (
                  <li key={r.id} className="flex items-center justify-between py-2">
                    <span className="text-slate-700">{r.title}</span>
                    {r.url && (
                      <a
                        href={r.url}
                        target="_blank"
                        rel="noreferrer"
                        className="text-blue-600 hover:underline"
                      >
                        Watch
                      </a>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          );
        })}
        {groups.data?.length !== undefined &&
          resourceQueries.every((q) => !q.isLoading && (q.data?.length ?? 0) === 0) && (
            <p className="text-sm text-slate-500">No recordings shared yet.</p>
          )}
      </div>
    </div>
  );
}
