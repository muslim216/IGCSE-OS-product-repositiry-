import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { followTarget, SETTLE_MS } from "../tutor/SectionedPage";

// A section that grows as the ones above it load: its top edge moves between
// ticks. jsdom has no layout, so the position is faked.
let top = 0;
let target: HTMLElement;
const scroll = vi.fn();

beforeEach(() => {
  vi.useFakeTimers();
  top = 400;
  scroll.mockReset();
  target = document.createElement("section");
  target.id = "boundaries";
  target.tabIndex = -1;
  target.getBoundingClientRect = () => ({ top }) as DOMRect;
  target.scrollIntoView = scroll;
  document.body.append(target);
});

afterEach(() => {
  target.remove();
  vi.useRealTimers();
});

test("scrolls again when the target moves, and focuses it once", () => {
  const stop = followTarget("boundaries");
  expect(scroll).toHaveBeenCalledTimes(1);
  expect(document.activeElement).toBe(target);

  vi.advanceTimersByTime(300);
  expect(scroll).toHaveBeenCalledTimes(1);

  top = 900;
  vi.advanceTimersByTime(200);
  expect(scroll).toHaveBeenCalledTimes(2);
  stop();
});

test("stops following once the reader scrolls", () => {
  followTarget("boundaries");
  expect(scroll).toHaveBeenCalledTimes(1);

  window.dispatchEvent(new Event("wheel"));
  top = 900;
  vi.advanceTimersByTime(500);
  expect(scroll).toHaveBeenCalledTimes(1);
});

test.each(["keydown", "touchstart"])("stops following on %s", (type) => {
  followTarget("boundaries");
  window.dispatchEvent(new Event(type));
  top = 900;
  vi.advanceTimersByTime(500);
  expect(scroll).toHaveBeenCalledTimes(1);
});

test("stops following after the settle window", () => {
  followTarget("boundaries");
  vi.advanceTimersByTime(SETTLE_MS + 200);
  top = 900;
  vi.advanceTimersByTime(500);
  expect(scroll).toHaveBeenCalledTimes(1);
});
