import { expect, test } from "vitest";
import { TIME_OPTIONS, formatSlot, formatTime } from "../lib/schedule";

/* Lesson times read the same everywhere: the Today page prints the API's own
   "HH:MM", so the class pages must not turn the same lesson into "5:00 PM". */

test("times are 24-hour and drop the seconds the API sends back", () => {
  expect(formatTime("17:00:00")).toBe("17:00");
  expect(formatTime("09:30")).toBe("09:30");
  expect(formatTime("7:05")).toBe("07:05");
});

test("a slot is a short weekday and a 24-hour time", () => {
  expect(formatSlot(0, "17:00:00")).toBe("Mon 17:00");
});

test("the start-time picker labels match the stored value", () => {
  for (const option of TIME_OPTIONS) expect(option.label).toBe(option.value);
});
