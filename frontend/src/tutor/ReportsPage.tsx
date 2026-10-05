import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { FileBarChart } from "lucide-react";
import { listGroups } from "../api/groups";
import { buttonClasses } from "../components/controls";
import { ErrorState, PageHeader, PageSkeleton } from "../components/page";
import { EmptyState, SectionCard } from "../components/ui";

/**
 * Reports, the tutor's top-level tab: one report per class. The report is the
 * tutor's own document, built around the class's teaching plan; the parent's
 * report is a different document and lives elsewhere.
 */
export default function ReportsPage() {
  const groups = useQuery({ queryKey: ["groups"], queryFn: listGroups });

  return (
    <div>
      <PageHeader
        title="Reports"
        description="Where each class stands against its teaching plan, what it has covered, the mistakes that keep coming up, and who is attending."
      />
      {groups.isLoading ? (
        <PageSkeleton rows={3} label="Loading your classes" />
      ) : groups.isError ? (
        <ErrorState
          title="Your classes didn't load"
          error={groups.error}
          onRetry={() => groups.refetch()}
        />
      ) : !groups.data || groups.data.length === 0 ? (
        <SectionCard>
          <EmptyState
            title="You haven't set up a class yet."
            hint="A report is written for a class. Create one and it appears here."
            action={
              <Link to="/tutor/classes" className={buttonClasses("primary", "md")}>
                Go to your classes
              </Link>
            }
          />
        </SectionCard>
      ) : (
        <ul className="space-y-3">
          {groups.data.map((g) => (
            <li key={g.id}>
              <Link
                to={`/tutor/reports/${g.id}`}
                className="avora-card flex items-center justify-between gap-4 rounded-xl border border-line bg-surface p-5"
              >
                <span className="min-w-0">
                  <span className="block font-display text-lg text-ink-900">{g.name}</span>
                  <span className="block text-sm text-ink-500">
                    {g.subject.name} · {g.member_count}{" "}
                    {g.member_count === 1 ? "learner" : "learners"}
                  </span>
                </span>
                <span className="flex shrink-0 items-center gap-2 text-sm text-brand-600">
                  <FileBarChart aria-hidden className="h-4 w-4" />
                  Open report
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
