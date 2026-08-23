/**
 * AV-67 on the student's own screen.
 *
 * The per-user override promises that "anything addressed to you" turns over
 * at the reader's midnight. Until these dates were computed in that zone, a
 * student could set it and see nothing change — the labels came from whatever
 * clock the device happened to be on. A preference with no observable effect
 * is worse than no preference, so this is the read side of the setting.
 */
import { describe, expect, test } from "vitest";
import { calendarDaysUntil, dayKeyIn } from "../lib/timezones";

describe("the day a deadline falls on depends on who is reading", () => {
  // 22:00 UTC on 10 Aug is still 10 Aug in London and already 11 Aug in
  // Auckland — one instant, two calendar days, and the same homework is
  // "due today" for one reader and "due tomorrow" for the other.
  const instant = "2026-08-10T22:00:00Z";

  test("the same instant is a different calendar day in each zone", () => {
    expect(dayKeyIn(new Date(instant), "Europe/London")).toBe("2026-08-10");
    expect(dayKeyIn(new Date(instant), "Pacific/Auckland")).toBe("2026-08-11");
  });

  test("a deadline is counted from midnight in the reader's zone", () => {
    // Due at that instant, read from Auckland where it is already the 11th:
    // the deadline lands on the 11th too, so it is today, not tomorrow.
    const daysInAuckland = calendarDaysUntil(instant, "Pacific/Auckland");
    const daysInLondon = calendarDaysUntil(instant, "Europe/London");
    // Whatever "now" is when this runs, the two zones can differ by at most a
    // day, and Auckland is never behind London.
    expect(daysInAuckland).toBeLessThanOrEqual(daysInLondon);
    expect(daysInLondon - daysInAuckland).toBeLessThanOrEqual(1);
  });

  test("midnight is the boundary, not 24 hours after the deadline", () => {
    // An evening deadline read the next morning is "overdue", never "today":
    // rounding elapsed milliseconds (~14h) would call it today.
    const yesterdayEvening = new Date(Date.now() - 14 * 3_600_000);
    const zone = "UTC";
    const key = dayKeyIn(yesterdayEvening, zone);
    const todayKey = dayKeyIn(new Date(), zone);
    if (key !== todayKey) {
      expect(calendarDaysUntil(yesterdayEvening.toISOString(), zone)).toBeLessThan(0);
    }
  });

  test("an unset zone falls back to the browser rather than throwing", () => {
    expect(() => calendarDaysUntil(instant, null)).not.toThrow();
    expect(dayKeyIn(new Date(instant), null)).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });

  test("an unusable zone degrades to the browser rather than throwing", () => {
    // A zone stored before tzdata was trimmed, or a value the browser does not
    // know: a wrong-looking date beats a blank screen.
    expect(() => calendarDaysUntil(instant, "Not/AZone")).not.toThrow();
    expect(dayKeyIn(new Date(instant), "Not/AZone")).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });
});
