import { useQueries, useQuery } from "@tanstack/react-query";
import { ExternalLink, Video } from "lucide-react";
import { ErrorState, PageHeader, SectionSkeleton } from "../components/page";
import { EmptyState, SectionCard } from "../components/ui";
import { myGroups } from "../api/groups";
import { isSafeHttpUrl, listResources } from "../api/resources";

export default function RecordingsPage() {
  const groups = useQuery({ queryKey: ["my-groups"], queryFn: myGroups });
  const resourceQueries = useQueries({
    queries: (groups.data ?? []).map((g) => ({
      queryKey: ["resources", g.id, "recording"],
      queryFn: () => listResources(g.id, "recording"),
      enabled: groups.data !== undefined,
    })),
  });

  const loading = groups.isPending || resourceQueries.some((q) => q.isPending);
  // A failed list is stated, never shown as "no recordings shared yet" — that
  // would be a claim about the tutor made from a request that never answered.
  const failed = groups.isError || resourceQueries.some((q) => q.isError);
  const shelves = (groups.data ?? [])
    .map((g, i) => ({ group: g, recordings: resourceQueries[i]?.data ?? [] }))
    .filter((s) => s.recordings.length > 0);

  return (
    <div className="max-w-3xl space-y-6">
      <PageHeader title="Recordings" description="Lesson recordings your tutors have shared." />

      {loading ? (
        <SectionCard>
          <SectionSkeleton rows={3} label="Loading recordings" />
        </SectionCard>
      ) : failed ? (
        <ErrorState
          title="Couldn't load your recordings."
          error={groups.error ?? resourceQueries.find((q) => q.isError)?.error}
          onRetry={() => {
            void groups.refetch();
            resourceQueries.forEach((q) => void q.refetch());
          }}
        />
      ) : shelves.length === 0 ? (
        <SectionCard>
          <EmptyState
            title="No recordings shared yet."
            hint="When your tutor shares a lesson recording, it will appear here."
          />
        </SectionCard>
      ) : (
        shelves.map(({ group, recordings }) => (
          <SectionCard key={group.id}>
            <h2 className="font-display text-lg text-ink-900">{group.name}</h2>
            <ul className="mt-2 divide-y divide-line border-t border-line text-sm">
              {recordings.map((r) => (
                <li key={r.id} className="flex items-center justify-between gap-3 py-2.5">
                  <span className="flex min-w-0 items-center gap-2 text-ink-900">
                    <Video aria-hidden className="h-4 w-4 shrink-0 text-ink-500" />
                    <span className="truncate">{r.title}</span>
                  </span>
                  {isSafeHttpUrl(r.url) && (
                    <a
                      href={r.url}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex shrink-0 items-center gap-1 font-medium text-brand-600 hover:text-brand-700"
                    >
                      Watch
                      <ExternalLink aria-hidden className="h-3.5 w-3.5" />
                      <span className="sr-only">(opens in a new tab)</span>
                    </a>
                  )}
                </li>
              ))}
            </ul>
          </SectionCard>
        ))
      )}
    </div>
  );
}
