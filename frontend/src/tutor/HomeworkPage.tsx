import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ChevronRight } from "lucide-react";
import { myOrganization } from "../api/auth";
import { listMyHomework, type TutorHomework } from "../api/homework";
import { useMyTimezone } from "../auth/AuthContext";
import { ErrorState, PageHeader, SectionSkeleton } from "../components/page";
import { EmptyState, SectionCard } from "../components/ui";
import { assignmentStatus } from "../lib/assignmentStatus";
import { formatDayMonth } from "../lib/timezones";

const linkClass = "font-medium text-brand-600 hover:text-brand-700";

/** In the same zone a student sees the due date in, so both name the same day:
 *  the tutor's own, else the organization's (the order the Overview uses). */
function dueLabel(dueAt: string | null, timeZone: string | null): string {
  if (!dueAt) return "No due date";
  return `Due ${formatDayMonth(new Date(dueAt), timeZone)}`;
}

/** Hand-ins only mean something once students could have submitted: a draft is
 *  still being checked, and a class with nobody in it has no "of". Those cases
 *  say so rather than printing "0 of 0". */
function progressLabel(row: TutorHomework): string | null {
  if (row.status !== "published" && row.status !== "closed") return null;
  if (row.enrolled_count === 0) return "No students yet";
  return `${row.submitted_count} of ${row.enrolled_count} handed in · ${row.marked_count} marked`;
}

function HomeworkRow({ row, timeZone }: { row: TutorHomework; timeZone: string | null }) {
  const status = assignmentStatus(row.status);
  const progress = progressLabel(row);
  return (
    <li>
      <Link
        to={`/tutor/assignments/${row.id}`}
        className="flex items-center justify-between gap-3 px-5 py-3.5 transition-colors hover:bg-surface-muted"
      >
        <span className="min-w-0">
          <span className="block truncate font-medium text-ink-900">{row.title}</span>
          <span className="block break-words text-sm text-ink-500">
            {row.group_name} · {dueLabel(row.due_at, timeZone)}
          </span>
          {progress && <span className="block text-sm text-ink-700">{progress}</span>}
        </span>
        <span className="flex shrink-0 items-center gap-2">
          <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${status.classes}`}>
            {status.label}
          </span>
          <ChevronRight aria-hidden className="h-4 w-4 text-ink-500" />
        </span>
      </Link>
    </li>
  );
}

export default function HomeworkPage() {
  const homework = useQuery({ queryKey: ["homework", "mine"], queryFn: listMyHomework });
  const myZone = useMyTimezone();
  const org = useQuery({
    queryKey: ["my-organization"],
    queryFn: myOrganization,
    enabled: !myZone,
  });
  const timeZone = myZone || (org.isSuccess ? org.data.timezone || "UTC" : null);

  return (
    <div>
      <PageHeader
        title="Homework"
        description="Every piece of homework across your classes, newest first."
      />
      {homework.isLoading ? (
        <SectionSkeleton rows={5} label="Loading homework" />
      ) : homework.isError ? (
        // A failed load must not read as "no homework yet".
        <ErrorState
          title="Couldn't load your homework"
          error={homework.error}
          onRetry={() => homework.refetch()}
        />
      ) : homework.data && homework.data.items.length > 0 ? (
        <>
          <ul className="divide-y divide-line overflow-hidden rounded-xl border border-line bg-surface">
            {homework.data.items.map((row) => (
              <HomeworkRow key={row.id} row={row} timeZone={timeZone} />
            ))}
          </ul>
          {homework.data.truncated && (
            <p className="mt-3 text-xs text-ink-500">
              Showing the {homework.data.limit} most recent. Older homework is in each class&apos;s
              Homework tab.
            </p>
          )}
        </>
      ) : (
        <SectionCard>
          <EmptyState
            title="No homework yet"
            hint="Homework is set from inside a class."
            action={
              <Link to="/tutor/classes" className={linkClass}>
                Go to Classes
              </Link>
            }
          />
        </SectionCard>
      )}
    </div>
  );
}
