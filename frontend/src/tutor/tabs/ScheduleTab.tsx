import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { WEEKDAYS, createLesson, deleteLesson, listLessons } from "../../api/groups";
import {
  DURATION_OPTIONS,
  TIME_OPTIONS,
  WEEKDAY_OPTIONS,
  formatDuration,
  formatTime,
} from "../../lib/schedule";
import { useGroupContext } from "../GroupLayout";
import { Button, Card, CardBody, CardHeader, EmptyState, Field, Input, Select } from "../../ui";

export default function ScheduleTab() {
  const { groupId } = useGroupContext();
  const queryClient = useQueryClient();
  const lessons = useQuery({
    queryKey: ["lessons", groupId],
    queryFn: () => listLessons(groupId),
  });

  const [form, setForm] = useState({
    weekday: 0,
    start_time: "17:00",
    duration_min: 60,
    title: "",
  });

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ["lessons", groupId] });
    // The class card and header show the next lesson, so they go stale too.
    queryClient.invalidateQueries({ queryKey: ["group", groupId] });
    queryClient.invalidateQueries({ queryKey: ["groups"] });
  };

  const addLesson = useMutation({
    mutationFn: () => createLesson(groupId, { ...form, title: form.title || null }),
    onSuccess: () => {
      refresh();
      setForm((f) => ({ ...f, title: "" }));
    },
  });
  const dropLesson = useMutation({
    mutationFn: (lessonId: number) => deleteLesson(groupId, lessonId),
    onSuccess: refresh,
  });

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    addLesson.mutate();
  }

  const sorted = [...(lessons.data ?? [])].sort(
    (a, b) => a.weekday - b.weekday || a.start_time.localeCompare(b.start_time),
  );

  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_22rem]">
      <div>
        <h3 className="font-semibold text-slate-900">Weekly timetable</h3>
        {sorted.length === 0 ? (
          <EmptyState
            className="mt-4"
            icon="🗓️"
            title="No lessons scheduled"
            description="Add the class's weekly slots and students will see when they next meet you."
          />
        ) : (
          <Card className="mt-4">
            <ul className="divide-y divide-slate-100">
              {sorted.map((lesson) => (
                <li key={lesson.id} className="flex items-center justify-between gap-3 px-5 py-3">
                  <div className="min-w-0">
                    <div className="font-medium text-slate-800">
                      {WEEKDAYS[lesson.weekday]} · {formatTime(lesson.start_time)}
                    </div>
                    <div className="text-sm text-slate-500">
                      {formatDuration(lesson.duration_min)}
                      {lesson.title && ` — ${lesson.title}`}
                    </div>
                  </div>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => dropLesson.mutate(lesson.id)}
                    disabled={dropLesson.isPending}
                  >
                    Remove
                  </Button>
                </li>
              ))}
            </ul>
          </Card>
        )}
      </div>

      <Card className="h-fit">
        <CardHeader title="Add a lesson" description="Repeats every week." />
        <CardBody>
          <form onSubmit={onSubmit} className="space-y-3">
            <Field label="Day">
              {(props) => (
                <Select
                  {...props}
                  options={WEEKDAY_OPTIONS}
                  value={form.weekday}
                  onChange={(e) => setForm({ ...form, weekday: Number(e.target.value) })}
                />
              )}
            </Field>
            <Field label="Starts at">
              {(props) => (
                <Select
                  {...props}
                  options={TIME_OPTIONS}
                  value={form.start_time}
                  onChange={(e) => setForm({ ...form, start_time: e.target.value })}
                />
              )}
            </Field>
            <Field label="Lasts">
              {(props) => (
                <Select
                  {...props}
                  options={DURATION_OPTIONS}
                  value={form.duration_min}
                  onChange={(e) => setForm({ ...form, duration_min: Number(e.target.value) })}
                />
              )}
            </Field>
            <Field label="Title" hint="Optional — e.g. “Paper 2 practice”">
              {(props) => (
                <Input
                  {...props}
                  value={form.title}
                  onChange={(e) => setForm({ ...form, title: e.target.value })}
                  placeholder="Optional"
                />
              )}
            </Field>
            <Button type="submit" disabled={addLesson.isPending} className="w-full">
              {addLesson.isPending ? "Adding…" : "Add lesson"}
            </Button>
            {addLesson.isError && (
              <p className="text-sm text-risk-600">Could not add the lesson.</p>
            )}
          </form>
        </CardBody>
      </Card>
    </div>
  );
}
