import { describe, expect, it } from "vitest";
import { mistakeSourceLabel } from "../tutor/mistakeSourceLabel";

describe("mistakeSourceLabel", () => {
  it("never credits a model with seeded example data", () => {
    expect(mistakeSourceLabel("demo")).toBe("Example data");
  });

  it("keeps the two real sources as they were", () => {
    expect(mistakeSourceLabel("ai")).toBe("Tagged by AI");
    expect(mistakeSourceLabel("tutor")).toBe("Your call");
  });
});
