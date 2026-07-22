import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import CountdownTimer from "../components/arcade/CountdownTimer";

describe("CountdownTimer", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-07-22T00:00:00Z"));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  test("renders the initial remaining time", () => {
    const target = new Date(Date.now() + 90 * 1000).toISOString();
    render(<CountdownTimer target={target} />);
    expect(screen.getByText(/01M/)).toBeInTheDocument();
  });

  test("ticks down every second", () => {
    const target = new Date(Date.now() + 5 * 1000).toISOString();
    render(<CountdownTimer target={target} />);
    expect(screen.getByText(/05S/)).toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(screen.getByText(/04S/)).toBeInTheDocument();
  });

  test("shows TIME UP! once the target has passed", () => {
    const target = new Date(Date.now() - 1000).toISOString();
    render(<CountdownTimer target={target} />);
    expect(screen.getByText("TIME UP!")).toBeInTheDocument();
  });

  test("clears its interval on unmount", () => {
    const target = new Date(Date.now() + 60 * 1000).toISOString();
    const { unmount } = render(<CountdownTimer target={target} />);
    const before = vi.getTimerCount();
    expect(before).toBeGreaterThan(0);
    unmount();
    expect(vi.getTimerCount()).toBe(before - 1);
  });
});
