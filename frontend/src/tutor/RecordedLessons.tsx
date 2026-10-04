import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { listTaughtLessons } from "../api/lessons";
import { SectionCard } from "../components/ui";
import { Button } from "../components/controls";
import { ErrorState, SectionSkeleton } from "../components/page";
import AttendanceRegister from "./AttendanceRegister";

/** "2026-10-13" and "16:30:00" as written: a bare date and a wall-clock time are
 *  not instants, so no timezone conversion applies. */
function when(date: string, startTime: string | null): string {
  return startTime ? `${date} · ${startTime.slice(0, 5)}` : date;
}

/** How many recent lessons show on load. Each register is its own request, so a
 *  class with a term of lessons must not fetch every one when the tab opens. */
const RECENT = 3;

/** Lessons already taught, each with its attendance. In-person lessons get a
 *  register; online ones will take attendance from Zoom or Google Meet. */
export default function RecordedLessons({ groupId }: { groupId: number }) {
  const [showAll, setShowAll] = useState(false);
  const lessons = useQuery({
    queryKey: ["taught-lessons", groupId],
    queryFn: () => listTaughtLessons(groupId),
  });

  if (lessons.isLoading) return <SectionSkeleton rows={2} label="Loading recorded lessons" />;
  if (lessons.isError) {
    return (
      <ErrorState
        title="Recorded lessons didn't load"
        error={lessons.error}
        onRetry={() => lessons.refetch()}
      />
    );
  }
  const items = lessons.data ?? [];
  if (items.length === 0) return null;

  return (
    <div className="space-y-3">
      <h2 className="text-lg text-ink-900">Recorded lessons</h2>
      {(showAll ? items : items.slice(0, RECENT)).map((lesson) => (
        <SectionCard key={lesson.id}>
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h3 className="font-medium text-ink-900">{when(lesson.date, lesson.start_time)}</h3>
            <span className="text-sm text-ink-500">
              {lesson.mode === "online" ? "Online" : "In person"}
            </span>
          </div>
          <div className="mt-3">
            {lesson.mode === "online" ? (
              <p className="text-sm text-ink-500">
                Attendance comes from Zoom or Google Meet — not connected yet.
              </p>
            ) : (
              <AttendanceRegister lessonId={lesson.id} />
            )}
          </div>
        </SectionCard>
      ))}
      {!showAll && items.length > RECENT && (
        <Button variant="secondary" size="sm" onClick={() => setShowAll(true)}>
          Show {items.length - RECENT} older {items.length - RECENT === 1 ? "lesson" : "lessons"}
        </Button>
      )}
    </div>
  );
}
