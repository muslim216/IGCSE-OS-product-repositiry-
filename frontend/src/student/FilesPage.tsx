import { useQueries, useQuery } from "@tanstack/react-query";
import { AuthFileLink } from "../components/AuthFile";
import { myGroups } from "../api/groups";
import { listResources, resourceFilePath } from "../api/resources";

export default function FilesPage() {
  const groups = useQuery({ queryKey: ["my-groups"], queryFn: myGroups });
  const resourceQueries = useQueries({
    queries: (groups.data ?? []).map((g) => ({
      queryKey: ["resources", g.id, "file"],
      queryFn: () => listResources(g.id, "file"),
      enabled: groups.data !== undefined,
    })),
  });

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-xl font-semibold text-slate-800">Files</h2>
        <p className="text-sm text-slate-500">Notes and documents your tutors have shared.</p>
      </div>

      <div className="space-y-4">
        {(groups.data ?? []).map((g, i) => {
          const files = resourceQueries[i]?.data ?? [];
          if (files.length === 0) return null;
          return (
            <div key={g.id} className="rounded-lg border bg-white p-4">
              <h3 className="font-medium text-slate-800">{g.name}</h3>
              <ul className="mt-2 divide-y text-sm">
                {files.map((f) => (
                  <li key={f.id} className="flex items-center justify-between py-2">
                    <span className="text-slate-700">{f.title}</span>
                    <AuthFileLink path={resourceFilePath(f.id)} label="Open" />
                  </li>
                ))}
              </ul>
            </div>
          );
        })}
        {groups.data?.length !== undefined &&
          resourceQueries.every((q) => (q.data?.length ?? 0) === 0) && (
            <p className="text-sm text-slate-500">No files shared yet.</p>
          )}
      </div>
    </div>
  );
}
