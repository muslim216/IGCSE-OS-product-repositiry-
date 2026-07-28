import { WEEKDAYS } from "../api/groups";

/** Lessons repeat weekly, so a slot is a weekday plus a wall-clock start time. */

export interface SelectOption<T extends string | number> {
  value: T;
  label: string;
}

export const WEEKDAY_OPTIONS: SelectOption<number>[] = WEEKDAYS.map((label, value) => ({
  value,
  label,
}));

export const DURATION_OPTIONS: SelectOption<number>[] = [
  { value: 30, label: "30 minutes" },
  { value: 45, label: "45 minutes" },
  { value: 60, label: "1 hour" },
  { value: 90, label: "1 hour 30" },
  { value: 120, label: "2 hours" },
  { value: 180, label: "3 hours" },
];

/** "17:00" / "17:00:00" -> "5:00 PM". Tolerates the seconds the API sends back. */
export function formatTime(value: string): string {
  const [rawHour, minute] = value.split(":");
  const hour = Number(rawHour);
  const suffix = hour < 12 ? "AM" : "PM";
  const display = hour % 12 === 0 ? 12 : hour % 12;
  return `${display}:${minute} ${suffix}`;
}

/** Quarter-hour slots across a plausible teaching day, as a dropdown. */
export const TIME_OPTIONS: SelectOption<string>[] = Array.from({ length: 4 * 17 }, (_, i) => {
  const minutes = 6 * 60 + i * 15; // 06:00 through 22:45
  const value = `${String(Math.floor(minutes / 60)).padStart(2, "0")}:${String(
    minutes % 60,
  ).padStart(2, "0")}`;
  return { value, label: formatTime(value) };
});

export function formatDuration(minutes: number): string {
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest ? `${hours}h ${rest}m` : `${hours}h`;
}

/** Compact slot label for cards: "Tue 5:00 PM". */
export function formatSlot(weekday: number, startTime: string): string {
  return `${WEEKDAYS[weekday]?.slice(0, 3) ?? "?"} ${formatTime(startTime)}`;
}
