import { useQueries, useQuery } from "@tanstack/react-query";
import { FileText } from "lucide-react";
import { AuthFileLink } from "../components/AuthFile";
import { ErrorState, PageHeader, SectionSkeleton } from "../components/page";
import { EmptyState, SectionCard } from "../components/ui";
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

  const loading = groups.isPending || resourceQueries.some((q) => q.isPending);
  // A class whose list failed is not a class with no files: claiming "no files
  // shared yet" over a failed request would tell a student their tutor shared
  // nothing when we simply could not ask.
  const failed = groups.isError || resourceQueries.some((q) => q.isError);
  const shelves = (groups.data ?? [])
    .map((g, i) => ({ group: g, files: resourceQueries[i]?.data ?? [] }))
    .filter((s) => s.files.length > 0);

  return (
    <div className="max-w-3xl space-y-6">
      <PageHeader title="Files" description="Notes and documents your tutors have shared." />

      {loading ? (
        <SectionCard>
          <SectionSkeleton rows={3} label="Loading files" />
        </SectionCard>
      ) : failed ? (
        <ErrorState
          title="Couldn't load your files."
          error={groups.error ?? resourceQueries.find((q) => q.isError)?.error}
          onRetry={() => {
            void groups.refetch();
            resourceQueries.forEach((q) => void q.refetch());
          }}
        />
      ) : shelves.length === 0 ? (
        <SectionCard>
          <EmptyState
            title="No files shared yet."
            hint="When your tutor shares notes or documents, they'll appear here."
          />
        </SectionCard>
      ) : (
        shelves.map(({ group, files }) => (
          <SectionCard key={group.id}>
            <h2 className="font-display text-lg text-ink-900">{group.name}</h2>
            <ul className="mt-2 divide-y divide-line border-t border-line text-sm">
              {files.map((f) => (
                <li key={f.id} className="flex items-center justify-between gap-3 py-2.5">
                  <span className="flex min-w-0 items-center gap-2 text-ink-900">
                    <FileText aria-hidden className="h-4 w-4 shrink-0 text-ink-500" />
                    <span className="truncate">{f.title}</span>
                  </span>
                  <AuthFileLink path={resourceFilePath(f.id)} label="Open" />
                </li>
              ))}
            </ul>
          </SectionCard>
        ))
      )}
    </div>
  );
}
