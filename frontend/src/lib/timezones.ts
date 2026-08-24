/** Zone helpers shared by the organization picker and the per-user one.
 *
 * They live here rather than in either component because the per-user control
 * (AV-67) is mounted for students and parents too, and a shared control
 * reaching into `tutor/` for its list would invert the folder layering the
 * first time someone moved a file.
 */

/** Every zone the pickers offer.
 *
 * Intl.supportedValuesOf is recent enough that it may be absent; when it is,
 * the control degrades to offering UTC and the detected zone alone rather than
 * disappearing. A short list is a smaller UI, not a broken one.
 *
 * UTC is added because that list does not contain it — V8 returns 418 zones
 * and neither `UTC` nor `Etc/UTC` is among them. The organization control tells
 * an unset tutor that "days are worked out in UTC", so UTC is a zone this
 * product names to users and one the API accepts (`available_timezones()`
 * carries it); a tutor who wants to pin it deliberately, rather than leave the
 * setting unset, could not choose it from a list built on the browser alone. */
export function supportedTimezones(): string[] {
  const intl = Intl as unknown as { supportedValuesOf?: (key: string) => string[] };
  let zones: string[];
  try {
    zones = intl.supportedValuesOf?.("timeZone") ?? [];
  } catch {
    zones = [];
  }
  return zones.includes("UTC") ? zones : [...zones, "UTC"];
}

export function detectedTimezone(): string | null {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || null;
  } catch {
    return null;
  }
}

/** The calendar day an instant falls on, in `timeZone`, as `YYYY-MM-DD`.
 *
 * en-CA because it formats as ISO; the locale is a formatting detail, not a
 * user-facing choice. An unset or unusable zone falls back to the browser's,
 * which is what every date on these screens used before the per-user override
 * existed — so a user who has set nothing sees exactly what they saw. */
export function dayKeyIn(instant: Date, timeZone?: string | null): string {
  const options: Intl.DateTimeFormatOptions = {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  };
  try {
    return new Intl.DateTimeFormat("en-CA", {
      ...options,
      timeZone: timeZone ?? undefined,
    }).format(instant);
  } catch {
    return new Intl.DateTimeFormat("en-CA", options).format(instant);
  }
}

/** A short `5 Sep` style date, rendered in `timeZone`.
 *
 * Every Intl call that takes a zone needs the same guard: an unusable stored
 * zone makes the constructor throw `RangeError`, and one unrendered label would
 * take the whole screen down with it. `calendarDaysUntil` degrades already; a
 * date further out than tomorrow goes through here, so it has to as well. */
export function formatDayMonth(instant: Date, timeZone?: string | null): string {
  const options: Intl.DateTimeFormatOptions = { day: "numeric", month: "short" };
  try {
    return instant.toLocaleDateString(undefined, { ...options, timeZone: timeZone ?? undefined });
  } catch {
    return instant.toLocaleDateString(undefined, options);
  }
}

/** Whole calendar days from today to `dueAt`, counted in `timeZone`.
 *
 * By midnight boundaries rather than elapsed milliseconds, so "due today" and
 * "due tomorrow" turn over at midnight rather than 24 hours after the
 * deadline — Math.round over elapsed time mislabels an evening deadline the
 * next morning (~14h reads as "today", not "tomorrow").
 *
 * The zone is the reader's own (AV-67): a student who has told us they are in
 * Dubai should see Dubai's midnight decide what is due today, whatever clock
 * the device in front of them is set to. */
export function calendarDaysUntil(dueAt: string, timeZone?: string | null): number {
  const dueDay = dayKeyIn(new Date(dueAt), timeZone);
  const today = dayKeyIn(new Date(), timeZone);
  // Both are midnight-anchored day keys, so parsing them as UTC compares whole
  // days without either zone's offset re-entering the arithmetic.
  return Math.round(
    (Date.parse(`${dueDay}T00:00:00Z`) - Date.parse(`${today}T00:00:00Z`)) / 86_400_000,
  );
}
