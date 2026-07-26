import { Link } from "react-router-dom";
import type { UpcomingLesson } from "../../api/groups";
import { EmptyState, SectionCard, SectionHeader } from "../../components/ui";

function nextSessionId(lessons: UpcomingLesson[]): number | null {
  const now = new Date();
  const hhmm = `${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")}`;
  const upcoming = lessons.find((l) => l.start_time.slice(0, 5) >= hhmm);
  return upcoming?.id ?? null;
}

export default function TeachingRhythm({
  lessons,
  isLoading,
  isError,
}: {
  lessons: UpcomingLesson[] | undefined;
  isLoading: boolean;
  isError: boolean;
}) {
  const items = lessons ?? [];
  const nextId = nextSessionId(items);

  return (
    <SectionCard>
      <SectionHeader
        title="Teaching rhythm"
        description="Today's sessions, in order"
        action={
          <Link to="/tutor/classes" className="font-medium text-brand-600 hover:text-brand-700">
            Manage schedule →
          </Link>
        }
      />

      {isLoading ? (
        <div className="mt-4 space-y-3" aria-hidden>
          {[0, 1].map((i) => (
            <span key={i} className="block h-10 w-full animate-pulse rounded bg-surface-muted" />
          ))}
        </div>
      ) : isError ? (
        <EmptyState
          title="Today's sessions couldn't be loaded."
          hint="This is usually temporary — refresh the page to try again."
        />
      ) : items.length === 0 ? (
        <EmptyState
          title="No sessions today."
          hint="Your schedule is clear — a good moment for marking or planning the next lesson."
          action={
            <Link to="/tutor/classes" className="font-medium text-brand-600 hover:text-brand-700">
              Add lessons to a class →
            </Link>
          }
        />
      ) : (
        <ol className="mt-4">
          {items.map((lesson, i) => {
            const isNext = lesson.id === nextId;
            return (
              <li key={lesson.id} className="flex gap-4">
                <span className="w-12 shrink-0 pt-3 text-sm font-medium tabular-nums text-ink-900">
                  {lesson.start_time.slice(0, 5)}
                </span>
                <span aria-hidden className="flex w-3 shrink-0 flex-col items-center">
                  <span
                    className={`mt-4 h-2 w-2 shrink-0 rounded-full ${
                      isNext ? "bg-brand-600 ring-4 ring-brand-50" : "bg-line-strong"
                    }`}
                  />
                  {i < items.length - 1 && <span className="w-px flex-1 bg-line" />}
                </span>
                <span className="flex min-w-0 flex-1 flex-wrap items-baseline justify-between gap-x-4 gap-y-1 border-b border-line py-3 last:border-b-0">
                  <span className="min-w-0">
                    <span className="block font-medium text-ink-900">
                      {lesson.group_name}
                      {isNext && (
                        <span className="ml-2 rounded bg-brand-50 px-1.5 py-0.5 text-[11px] font-medium text-brand-700">
                          Up next
                        </span>
                      )}
                    </span>
                    <span className="block text-sm text-ink-500">
                      {lesson.subject_name} · {lesson.duration_min} min
                      {lesson.title ? ` · ${lesson.title}` : ""}
                    </span>
                  </span>
                  <Link
                    to={`/tutor/groups/${lesson.group_id}`}
                    className="shrink-0 text-sm font-medium text-brand-600 hover:text-brand-700"
                  >
                    Open class →
                  </Link>
                </span>
              </li>
            );
          })}
        </ol>
      )}
    </SectionCard>
  );
}
