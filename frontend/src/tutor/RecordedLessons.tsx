import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { listTaughtLessons, updateLesson, type TaughtLesson } from "../api/lessons";
import { SectionCard } from "../components/ui";
import { Button, Field, Input, Select } from "../components/controls";
import { friendlyError } from "../lib/errors";
import { ErrorState, SectionSkeleton } from "../components/page";
import AttendanceRegister from "./AttendanceRegister";
import OnlineAttendance from "./OnlineAttendance";

/** "2026-10-13" and "16:30:00" as written: a bare date and a wall-clock time are
 *  not instants, so no timezone conversion applies. */
function when(date: string, startTime: string | null): string {
  return startTime ? `${date} · ${startTime.slice(0, 5)}` : date;
}

/** How many recent lessons show on load. Each register is its own request, so a
 *  class with a term of lessons must not fetch every one when the tab opens. */
const RECENT = 3;

/** Lessons already taught, each with its attendance. In-person lessons get a
 *  register to mark; online ones take attendance from Zoom or Google Meet. */
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
          {lesson.origin === "plan" && (
            <p className="text-xs text-ink-500">Recorded from the plan</p>
          )}
          <LessonEdit lesson={lesson} groupId={groupId} />
          <div className="mt-3">
            {lesson.mode === "online" ? (
              <OnlineAttendance lessonId={lesson.id} />
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

/** Switch a recorded lesson between in person and online and set or clear its
 *  meeting link. A lesson recorded from the plan starts in person with no link, so
 *  without this its Zoom or Meet attendance could never be reached. */
function LessonEdit({ lesson, groupId }: { lesson: TaughtLesson; groupId: number }) {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [mode, setMode] = useState<"in_person" | "online">(lesson.mode);
  const [link, setLink] = useState(lesson.meeting_link ?? "");
  const [confirming, setConfirming] = useState(false);
  const save = useMutation({
    mutationFn: () =>
      updateLesson(
        lesson.id,
        // The server refuses a link on an in-person lesson, so none is sent.
        mode === "online" ? { mode, meeting_link: link.trim() || null } : { mode },
      ),
    onSuccess: () => {
      setEditing(false);
      queryClient.invalidateQueries({ queryKey: ["taught-lessons", groupId] });
      queryClient.invalidateQueries({ queryKey: ["lesson-meeting", lesson.id] });
      queryClient.invalidateQueries({ queryKey: ["lesson-attendance", lesson.id] });
      queryClient.invalidateQueries({ queryKey: ["student-attendance"] });
    },
  });
  // The server drops what was imported from the old meeting when the lesson goes in
  // person or its link changes, so say so before it happens.
  const dropsImport =
    lesson.meeting_provider != null &&
    (mode === "in_person" || (link.trim() || null) !== (lesson.meeting_link ?? null));

  if (!editing) {
    return (
      <Button
        size="sm"
        variant="ghost"
        onClick={() => {
          setMode(lesson.mode);
          setLink(lesson.meeting_link ?? "");
          save.reset();
          setConfirming(false);
          setEditing(true);
        }}
      >
        Edit
      </Button>
    );
  }
  return (
    <form
      className="mt-2 grid gap-3 sm:grid-cols-2"
      onSubmit={(e) => {
        e.preventDefault();
        if (dropsImport && !confirming) setConfirming(true);
        else save.mutate();
      }}
    >
      <Field label="Mode">
        <Select
          value={mode}
          onChange={(e) => {
            setMode(e.target.value as "in_person" | "online");
            setConfirming(false);
          }}
        >
          <option value="in_person">In person</option>
          <option value="online">Online</option>
        </Select>
      </Field>
      {mode === "online" && (
        <Field label="Meeting link" optional hint="Zoom or Google Meet, to fill in attendance">
          <Input
            type="text"
            value={link}
            placeholder="https://zoom.us/j/…"
            onChange={(e) => {
              setLink(e.target.value);
              setConfirming(false);
            }}
          />
        </Field>
      )}
      {confirming && (
        <p role="status" className="text-sm text-ink-700 sm:col-span-2">
          This removes the attendance imported from Zoom/Meet for this lesson. Marks you set
          yourself stay.
        </p>
      )}
      <div className="flex items-center gap-2 sm:col-span-2">
        <Button type="submit" size="sm" loading={save.isPending}>
          {confirming ? "Confirm" : "Save"}
        </Button>
        <Button type="button" size="sm" variant="ghost" onClick={() => setEditing(false)}>
          Cancel
        </Button>
      </div>
      {save.isError && (
        <p role="alert" className="text-sm text-risk-600 sm:col-span-2">
          {friendlyError(save.error)}
        </p>
      )}
    </form>
  );
}
