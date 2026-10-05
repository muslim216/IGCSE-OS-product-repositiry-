import { expect, test } from "vitest";
import { bandOf, greetingFor } from "../lib/readiness";

test("greetingFor tracks the time of day", () => {
  expect(greetingFor(8)).toBe("Good morning");
  expect(greetingFor(13)).toBe("Good afternoon");
  expect(greetingFor(20)).toBe("Good evening");
});

test("bandOf narrows a wire status and never invents one", () => {
  expect(bandOf("at_risk")).toBe("at_risk");
  expect(bandOf("not_enough_data")).toBeNull();
  expect(bandOf(undefined)).toBeNull();
  expect(bandOf(null)).toBeNull();
});

test("no module re-derives a band from a percentage (UX-28)", async () => {
  const mod = await import("../lib/readiness");
  expect("statusOf" in mod).toBe(false);
  expect("deriveLearnerRows" in mod).toBe(false);
});
