import { describe, expect, test } from "vitest";
import { gradeForPct } from "../lib/grades";

describe("gradeForPct", () => {
  test("boundary values map to the correct grade", () => {
    expect(gradeForPct(100)?.grade).toBe("A*");
    expect(gradeForPct(90)?.grade).toBe("A*");
    expect(gradeForPct(89.9)?.grade).toBe("A");
    expect(gradeForPct(80)?.grade).toBe("A");
    expect(gradeForPct(70)?.grade).toBe("B");
    expect(gradeForPct(60)?.grade).toBe("C");
    expect(gradeForPct(50)?.grade).toBe("D");
    expect(gradeForPct(40)?.grade).toBe("E");
    expect(gradeForPct(30)?.grade).toBe("F");
    expect(gradeForPct(20)?.grade).toBe("G");
    expect(gradeForPct(19)?.grade).toBe("U");
    expect(gradeForPct(0)?.grade).toBe("U");
  });

  test("null and undefined return null", () => {
    expect(gradeForPct(null)).toBeNull();
    expect(gradeForPct(undefined)).toBeNull();
  });

  test("out-of-range values are clamped", () => {
    expect(gradeForPct(150)?.grade).toBe("A*");
    expect(gradeForPct(-10)?.grade).toBe("U");
  });
});
