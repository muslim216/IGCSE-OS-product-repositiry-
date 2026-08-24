/**
 * AV-67 on the student's own screen.
 *
 * The per-user override promises that "anything addressed to you" turns over
 * at the reader's midnight. Until these dates were computed in that zone, a
 * student could set it and see nothing change — the labels came from whatever
 * clock the device happened to be on. A preference with no observable effect
 * is worse than no preference, so this is the read side of the setting.
 *
 * The clock is frozen throughout. Relative assertions ("Auckland is never
 * behind London") pass just as well when the zone is ignored entirely, which
 * is the regression these tests exist to catch.
 */
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { calendarDaysUntil, dayKeyIn, formatDayMonth } from "../lib/timezones";

// 11:00 UTC on 10 Aug 2026: mid-morning in London, 23:00 the same day in
// Auckland — so both readers are still on the 10th when "now" is taken.
const NOW = new Date("2026-08-10T11:00:00Z");

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(NOW);
});
afterEach(() => vi.useRealTimers());

describe("the day a deadline falls on depends on who is reading", () => {
  // 22:00 UTC on the 10th is still the 10th in London and already the 11th in
  // Auckland: one instant, two calendar days.
  const deadline = "2026-08-10T22:00:00Z";

  test("the same instant is a different calendar day in each zone", () => {
    expect(dayKeyIn(new Date(deadline), "Europe/London")).toBe("2026-08-10");
    expect(dayKeyIn(new Date(deadline), "Pacific/Auckland")).toBe("2026-08-11");
  });

  test("the reader's zone decides whether it is due today or tomorrow", () => {
    // London: deadline and today are both the 10th — today.
    expect(calendarDaysUntil(deadline, "Europe/London")).toBe(0);
    // Auckland: now is the 10th local, the deadline is the 11th — tomorrow.
    expect(calendarDaysUntil(deadline, "Pacific/Auckland")).toBe(1);
  });

  test("midnight is the boundary, not 24 hours after the deadline", () => {
    // 21:00 UTC on the 9th is ~14 hours before "now". Rounding elapsed time
    // would call that today; by calendar day it is yesterday, so it is overdue.
    expect(calendarDaysUntil("2026-08-09T21:00:00Z", "Europe/London")).toBe(-1);
  });

  test("an unset zone falls back to the browser rather than throwing", () => {
    expect(() => calendarDaysUntil(deadline, null)).not.toThrow();
    expect(dayKeyIn(new Date(deadline), null)).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });
});

describe("an unusable stored zone degrades instead of breaking the screen", () => {
  // A zone stored before tzdata was trimmed, or one this browser does not know.
  // Intl throws RangeError on the constructor, and one unrendered date label
  // would take the whole student home down with it.
  const unknown = "Not/AZone";

  test("the day count degrades to the browser's zone", () => {
    expect(() => calendarDaysUntil("2026-08-10T22:00:00Z", unknown)).not.toThrow();
    expect(dayKeyIn(new Date(), unknown)).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });

  test("a date beyond tomorrow still formats", () => {
    // The branch that actually threw: `due 5 Sep` goes through
    // toLocaleDateString with the same zone, which has its own constructor.
    const instant = new Date("2026-09-05T09:00:00Z");
    expect(() => formatDayMonth(instant, unknown)).not.toThrow();
    // And degrades to the browser's zone specifically — the same string the
    // screen showed before the per-user override existed.
    expect(formatDayMonth(instant, unknown)).toBe(
      instant.toLocaleDateString(undefined, { day: "numeric", month: "short" }),
    );
  });

  test("a valid zone still formats in that zone", () => {
    // 23:30 UTC on the 4th is already the 5th in Auckland and still the 4th in
    // New York. London is not the contrast here — it is on BST in September,
    // so 23:30 UTC is 00:30 on the 5th there too.
    //
    // Compared against the helper's own rendering of each day rather than the
    // literal "5" and "4": `formatDayMonth` passes `undefined` as the locale,
    // so the digits are the runtime's default — en-US under CI, but whatever
    // the developer's machine is set to locally, and plenty of locales render
    // these in non-Latin digits. Both sides move together under any locale;
    // the inequality is what keeps the comparison meaningful.
    const instant = new Date("2026-09-04T23:30:00Z");
    const fifth = formatDayMonth(new Date("2026-09-05T12:00:00Z"), "UTC");
    const fourth = formatDayMonth(new Date("2026-09-04T12:00:00Z"), "UTC");
    expect(fifth).not.toBe(fourth);
    expect(formatDayMonth(instant, "Pacific/Auckland")).toBe(fifth);
    expect(formatDayMonth(instant, "America/New_York")).toBe(fourth);
  });
});
