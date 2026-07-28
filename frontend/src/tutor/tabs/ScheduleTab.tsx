import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { WEEKDAYS, createLesson, deleteLesson, listLessons } from "../../api/groups";
import {
  DURATION_OPTIONS,
  TIME_OPTIONS,
  WEEKDAY_OPTIONS,
  formatDuration,
  formatTime,
} from "../../lib/schedule";
import { ApiError } from "../../api/client";
import { useGroupContext } from "../GroupLayout";
import { EmptyState, Modal } from "../../components/ui";

const selectClass = "rounded-md border border-line px-3 py-2 text-sm";

export default function ScheduleTab() {
  const { groupId } = useGroupContext();
  const queryClient = useQueryClient();
  const lessons = useQuery({ queryKey: ["lessons", groupId], queryFn: () => listLessons(groupId) });
  const [actionError, setActionError] = useState<string | null>(null);
  const [removing, setRemoving] = useState<{ id: number; label: string } | null>(null);
  const onError = (err: unknown) =>
    setActionError(err instanceof ApiError ? err.message : "Something went wrong. Try again.");

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
    onError,
  });
  const dropLesson = useMutation({
    mutationFn: (lessonId: number) => deleteLesson(groupId, lessonId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["lessons", groupId] });
      queryClient.invalidateQueries({ queryKey: ["group", groupId] });
      setRemoving(null);
    },
    onError,
  });

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    setActionError(null);
    addLesson.mutate();
  }

  return (
    <div>
      {actionError && <p className="mb-3 text-sm text-risk-600">{actionError}</p>}

      <div className="flex items-center justify-between">
        <h3 className="font-medium">Weekly lessons</h3>
        <Link
          to={`/tutor/groups/${groupId}/mock`}
          className="rounded-md border border-line px-3 py-1.5 text-sm hover:bg-slate-50"
        >
          Record mock/test
        </Link>
      </div>

      <ul className="mt-3 divide-y">
        {lessons.data?.map((lesson) => (
          <li key={lesson.id} className="flex items-center justify-between py-2 text-sm">
            <span>
              <span className="font-medium text-ink-700">{WEEKDAYS[lesson.weekday]}</span>{" "}
              {formatTime(lesson.start_time)} · {formatDuration(lesson.duration_min)}
              {lesson.title && <span className="text-ink-500"> — {lesson.title}</span>}
            </span>
            <button
              onClick={() =>
                setRemoving({
                  id: lesson.id,
                  label: `${WEEKDAYS[lesson.weekday]} ${formatTime(lesson.start_time)}`,
                })
              }
              className="text-red-500 hover:underline"
            >
              Remove
            </button>
          </li>
        ))}
      </ul>
      {lessons.data?.length === 0 && (
        <EmptyState
          title="No lessons scheduled"
          hint="Add the weekly slots below and students see them on their dashboard."
        />
      )}

      <form
        onSubmit={onSubmit}
        className="mt-3 flex flex-wrap items-end gap-2 border-t border-line pt-3"
      >
        <label className="block text-sm">
          <span className="mb-1 block text-xs font-medium text-ink-500">Day</span>
          <select
            className={selectClass}
            value={form.weekday}
            onChange={(e) => setForm({ ...form, weekday: Number(e.target.value) })}
          >
            {WEEKDAY_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
        <label className="block text-sm">
          <span className="mb-1 block text-xs font-medium text-ink-500">Starts</span>
          <select
            className={selectClass}
            value={form.start_time}
            onChange={(e) => setForm({ ...form, start_time: e.target.value })}
          >
            {TIME_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
        <label className="block text-sm">
          <span className="mb-1 block text-xs font-medium text-ink-500">Length</span>
          <select
            className={selectClass}
            value={form.duration_min}
            onChange={(e) => setForm({ ...form, duration_min: Number(e.target.value) })}
          >
            {DURATION_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
        <label className="block text-sm">
          <span className="mb-1 block text-xs font-medium text-ink-500">Title (optional)</span>
          <input
            className="rounded-md border border-line px-3 py-2 text-sm"
            placeholder="e.g. Paper 2 practice"
            value={form.title}
            onChange={(e) => setForm({ ...form, title: e.target.value })}
          />
        </label>
        <button
          type="submit"
          disabled={addLesson.isPending}
          className="rounded-md bg-brand-600 px-3 py-2 text-sm font-medium hover:bg-brand-700 disabled:opacity-50"
        >
          Add lesson
        </button>
      </form>

      <Modal
        open={removing !== null}
        onClose={() => setRemoving(null)}
        title={`Remove the ${removing?.label ?? ""} lesson?`}
      >
        <p className="text-sm text-ink-500">
          It disappears from this class's timetable and from students' dashboards.
        </p>
        <div className="mt-4 flex justify-end gap-2">
          <button
            onClick={() => setRemoving(null)}
            className="rounded-md border border-line px-3 py-1.5 text-sm hover:bg-slate-50"
          >
            Cancel
          </button>
          <button
            onClick={() => removing && dropLesson.mutate(removing.id)}
            disabled={dropLesson.isPending}
            className="rounded-md bg-red-600 px-3 py-1.5 text-sm font-medium disabled:opacity-50"
          >
            Remove
          </button>
        </div>
      </Modal>
    </div>
  );
}
