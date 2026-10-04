import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarClock } from "lucide-react";
import { WEEKDAYS, createLesson, deleteLesson, listLessons } from "../../api/groups";
import {
  DURATION_OPTIONS,
  TIME_OPTIONS,
  WEEKDAY_OPTIONS,
  formatDuration,
  formatTime,
} from "../../lib/schedule";
import { friendlyError } from "../../lib/errors";
import { useGroupContext } from "../GroupLayout";
import RecordLessonForm from "../RecordLessonForm";
import RecordedLessons from "../RecordedLessons";
import TeachingPlanInputs from "../TeachingPlanInputs";
import TeachingPlanView from "../TeachingPlanView";
import { EmptyState, SectionCard } from "../../components/ui";
import { Button, Field, Input, Select, buttonClasses } from "../../components/controls";
import { ConfirmDialog, ErrorState, SectionSkeleton } from "../../components/page";

export default function ScheduleTab() {
  const { group, groupId } = useGroupContext();
  const queryClient = useQueryClient();
  const lessons = useQuery({ queryKey: ["lessons", groupId], queryFn: () => listLessons(groupId) });
  const [actionError, setActionError] = useState<string | null>(null);
  const [removing, setRemoving] = useState<{ id: number; label: string } | null>(null);
  const onError = (err: unknown) => setActionError(friendlyError(err));

  const [form, setForm] = useState({
    weekday: 0,
    start_time: "17:00",
    duration_min: 60,
    title: "",
  });
  const addLesson = useMutation({
    mutationFn: () => createLesson(groupId, { ...form, title: form.title || null }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["lessons", groupId] });
      queryClient.invalidateQueries({ queryKey: ["group", groupId] });
    },
    onMutate: () => setActionError(null),
    onError,
  });
  const dropLesson = useMutation({
    mutationFn: (lessonId: number) => deleteLesson(groupId, lessonId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["lessons", groupId] });
      queryClient.invalidateQueries({ queryKey: ["group", groupId] });
      setRemoving(null);
    },
    onMutate: () => setActionError(null),
    onError,
  });

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    addLesson.mutate();
  }

  return (
    <div className="space-y-6">
      <RecordLessonForm key={`record-${groupId}`} groupId={groupId} subjectId={group.subject.id} />
      <RecordedLessons key={`recorded-${groupId}`} groupId={groupId} />

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg text-ink-900">Weekly lessons</h2>
          <p className="text-sm text-ink-500">Students see these on their dashboard.</p>
        </div>
        <Link to={`/tutor/groups/${groupId}/mock`} className={buttonClasses("secondary", "sm")}>
          Record mock or test marks
        </Link>
      </div>

      {actionError && (
        <p role="alert" className="rounded-md bg-risk-100 px-3 py-2 text-sm text-risk-600">
          {actionError}
        </p>
      )}

      {lessons.isLoading ? (
        <SectionSkeleton rows={3} label="Loading lessons" />
      ) : lessons.isError ? (
        <ErrorState
          title="The timetable didn't load"
          error={lessons.error}
          onRetry={() => lessons.refetch()}
        />
      ) : lessons.data && lessons.data.length > 0 ? (
        <ul className="divide-y divide-line rounded-xl border border-line bg-surface">
          {lessons.data.map((lesson) => {
            const label = `${WEEKDAYS[lesson.weekday]} ${formatTime(lesson.start_time)}`;
            return (
              <li key={lesson.id} className="flex items-center justify-between gap-3 px-4 py-3">
                <span className="flex min-w-0 items-center gap-3 text-sm">
                  <CalendarClock aria-hidden className="h-4 w-4 shrink-0 text-brand-600" />
                  <span className="min-w-0">
                    <span className="font-medium text-ink-900">{WEEKDAYS[lesson.weekday]}</span>{" "}
                    <span className="tabular-nums text-ink-700">
                      {formatTime(lesson.start_time)}
                    </span>
                    <span className="text-ink-500"> · {formatDuration(lesson.duration_min)}</span>
                    {lesson.title && <span className="text-ink-500"> — {lesson.title}</span>}
                  </span>
                </span>
                <Button
                  variant="ghost"
                  size="sm"
                  aria-label={`Remove the ${label} lesson`}
                  onClick={() => setRemoving({ id: lesson.id, label })}
                >
                  Remove
                </Button>
              </li>
            );
          })}
        </ul>
      ) : (
        <SectionCard>
          <EmptyState
            title="No lessons scheduled"
            hint="Add the weekly slots below and students see them on their dashboard."
          />
        </SectionCard>
      )}

      <SectionCard>
        <form onSubmit={onSubmit}>
          <h3 className="font-medium text-ink-900">Add a weekly lesson</h3>
          <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Field label="Day">
              <Select
                value={form.weekday}
                onChange={(e) => setForm({ ...form, weekday: Number(e.target.value) })}
              >
                {WEEKDAY_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Starts at">
              <Select
                value={form.start_time}
                onChange={(e) => setForm({ ...form, start_time: e.target.value })}
              >
                {TIME_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Length">
              <Select
                value={form.duration_min}
                onChange={(e) => setForm({ ...form, duration_min: Number(e.target.value) })}
              >
                {DURATION_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Title" optional>
              <Input
                placeholder="e.g. Paper 2 practice"
                value={form.title}
                onChange={(e) => setForm({ ...form, title: e.target.value })}
              />
            </Field>
          </div>
          <div className="mt-4 flex justify-end">
            <Button type="submit" loading={addLesson.isPending}>
              Add lesson
            </Button>
          </div>
        </form>
      </SectionCard>

      <TeachingPlanInputs key={groupId} groupId={groupId} />
      <TeachingPlanView key={`view-${groupId}`} groupId={groupId} subjectId={group.subject.id} />

      <ConfirmDialog
        open={removing !== null}
        title={`Remove the ${removing?.label ?? ""} lesson?`}
        body="It disappears from this class's timetable and from students' dashboards."
        confirmLabel="Remove lesson"
        danger
        busy={dropLesson.isPending}
        onConfirm={() => removing && dropLesson.mutate(removing.id)}
        onCancel={() => setRemoving(null)}
      />
    </div>
  );
}
