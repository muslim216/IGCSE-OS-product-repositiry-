import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ApiError } from "../../api/client";
import { WEEKDAYS, createLesson, type Group } from "../../api/groups";
import { Modal } from "../../components/ui";

const FIELD =
  "mt-1 w-full rounded-md border border-line-strong bg-surface px-3 py-2 text-sm text-ink-900 focus:border-brand-700 focus:outline-none";
const LABEL = "block text-sm text-ink-700";

export default function CreateLessonModal({
  open,
  onClose,
  groups,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  groups: Group[] | undefined;
  onCreated: () => void;
}) {
  const queryClient = useQueryClient();
  const [groupId, setGroupId] = useState<string>("");
  const [weekday, setWeekday] = useState("0");
  const [startTime, setStartTime] = useState("09:00");
  const [duration, setDuration] = useState("60");
  const [title, setTitle] = useState("");
  const [error, setError] = useState("");

  const options = groups ?? [];
  const selected = groupId || (options[0] ? String(options[0].id) : "");

  const mutation = useMutation({
    mutationFn: () =>
      createLesson(Number(selected), {
        weekday: Number(weekday),
        start_time: `${startTime}:00`,
        duration_min: Number(duration),
        title: title.trim() || null,
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["today-lessons"] });
      setTitle("");
      setError("");
      onCreated();
      onClose();
    },
    onError: (err) =>
      setError(
        err instanceof ApiError
          ? err.message
          : "The lesson couldn't be saved. Check the details and try again.",
      ),
  });

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!selected) {
      setError("Choose a class for this lesson.");
      return;
    }
    setError("");
    mutation.mutate();
  }

  return (
    <Modal open={open} onClose={onClose} title="Schedule a weekly lesson">
      <form onSubmit={submit} className="space-y-3">
        <p className="text-sm text-ink-500">
          Lessons repeat weekly. Today's sessions update as soon as it's saved.
        </p>

        <label className={LABEL}>
          Class
          <select
            required
            value={selected}
            onChange={(e) => setGroupId(e.target.value)}
            className={FIELD}
          >
            {options.length === 0 && <option value="">No classes yet</option>}
            {options.map((g) => (
              <option key={g.id} value={g.id}>
                {g.name} — {g.subject.name}
              </option>
            ))}
          </select>
        </label>

        <div className="grid grid-cols-2 gap-3">
          <label className={LABEL}>
            Day
            <select value={weekday} onChange={(e) => setWeekday(e.target.value)} className={FIELD}>
              {WEEKDAYS.map((day, i) => (
                <option key={day} value={i}>
                  {day}
                </option>
              ))}
            </select>
          </label>
          <label className={LABEL}>
            Start time
            <input
              type="time"
              required
              value={startTime}
              onChange={(e) => setStartTime(e.target.value)}
              className={FIELD}
            />
          </label>
        </div>

        <label className={LABEL}>
          Duration (minutes)
          <input
            type="number"
            min={15}
            step={5}
            required
            value={duration}
            onChange={(e) => setDuration(e.target.value)}
            className={FIELD}
          />
        </label>

        <label className={LABEL}>
          Focus (optional)
          <input
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="e.g. Quadratic functions"
            className={FIELD}
          />
        </label>

        {error && <p className="text-sm text-risk-600">{error}</p>}

        <div className="flex justify-end gap-2 pt-1">
          <button
            type="button"
            onClick={onClose}
            className="rounded-md px-3 py-2 text-sm text-ink-500 transition hover:bg-surface-muted hover:text-ink-900"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={mutation.isPending || options.length === 0}
            className="rounded-md bg-brand-600 px-4 py-2 text-sm font-medium text-canvas transition hover:bg-brand-700 disabled:opacity-50"
          >
            {mutation.isPending ? "Saving…" : "Schedule lesson"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
