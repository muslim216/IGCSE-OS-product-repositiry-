import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { FileText } from "lucide-react";
import { listPastPapers } from "../api/pastPapers";
import { ErrorState, PageHeader, SectionSkeleton } from "../components/page";
import { EmptyState, SectionCard } from "../components/ui";

export default function PastPapersPage() {
  const papers = useQuery({ queryKey: ["past-papers"], queryFn: () => listPastPapers() });

  return (
    <div className="max-w-3xl space-y-6">
      <PageHeader
        title="Past papers"
        description="Sit a full paper, then upload your answers to get it marked question by question."
      />

      {papers.isPending ? (
        <SectionCard>
          <SectionSkeleton rows={3} label="Loading past papers" />
        </SectionCard>
      ) : papers.isError ? (
        // A failed request is not an empty shelf: saying "no past papers" here
        // would tell a student there is nothing to sit when we simply could not ask.
        <ErrorState
          title="Couldn't load past papers."
          error={papers.error}
          onRetry={() => void papers.refetch()}
        />
      ) : papers.data.length === 0 ? (
        <SectionCard>
          <EmptyState
            title="No past papers have been added for your subjects yet."
            hint="When your tutor adds some, they'll appear here."
          />
        </SectionCard>
      ) : (
        <ul className="grid gap-3 sm:grid-cols-2">
          {papers.data.map((p) => (
            <li key={p.id}>
              <Link
                to={`/student/past-papers/${p.id}`}
                className="flex h-full gap-3 rounded-xl border border-line bg-surface p-4 shadow-[0_1px_2px_rgba(44,26,14,0.06)] transition-colors hover:border-brand-500"
              >
                <FileText aria-hidden className="mt-0.5 h-5 w-5 shrink-0 text-brand-600" />
                <span className="min-w-0">
                  <span className="block font-medium text-ink-900">{p.display_title}</span>
                  <span className="mt-1 block text-sm text-ink-500">
                    {p.total_marks ? `${p.total_marks} marks` : "Marks not set"}
                    {p.duration_minutes ? ` · ${p.duration_minutes} minutes` : ""}
                  </span>
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
