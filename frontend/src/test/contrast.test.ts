/**
 * UX-8 / UX-9: measured contrast, asserted rather than assumed.
 *
 * The palette carried a token, --color-ink-400, that could not legibly carry
 * the text it was being used for: 4.03 on canvas, 3.21 on surface and 2.82 on
 * surface-muted, against a 4.5:1 requirement, on 23 pieces of 11-14px copy.
 * Interactive controls had it worse — their border was --color-line at 1.21
 * against surface, which is a field edge a low-vision user cannot find.
 *
 * Fixing the values is half of it. Nothing stops the next palette tweak from
 * reintroducing the same failure, so these tests read the real tokens out of
 * index.css and do the WCAG arithmetic. They fail if a token moves below the
 * ratio its role requires.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, test } from "vitest";

// Read from disk rather than importing the stylesheet. The Tailwind plugin
// resolves a `?raw` CSS import to an empty string under vitest, which would
// make every assertion below pass vacuously against a file it never read —
// the exact failure mode a guard like this exists to avoid. Resolved from the
// vitest root (frontend/) because import.meta.url is an http: URL under jsdom.
const css = readFileSync(join(process.cwd(), "src", "index.css"), "utf8");

function token(name: string): string {
  const match = css.match(new RegExp(`--color-${name}:\\s*(#[0-9a-fA-F]{6})\\s*;`));
  if (!match) throw new Error(`--color-${name} is not defined in index.css`);
  return match[1];
}

/** WCAG 2.x relative luminance. */
function luminance(hex: string): number {
  const channels = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255);
  const [r, g, b] = channels.map((c) =>
    c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4,
  );
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function ratio(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

/** Every background a token can land on. The worst case is the real case. */
const SURFACES = ["canvas", "surface", "surface-muted"] as const;

describe("the arithmetic itself", () => {
  // A contrast guard that computes the wrong ratio guards nothing, so pin the
  // formula against two values whose answers are known independently.
  test("black on white is 21:1 and a colour against itself is 1:1", () => {
    expect(ratio("#000000", "#ffffff")).toBeCloseTo(21, 5);
    expect(ratio("#1c2543", "#1c2543")).toBeCloseTo(1, 5);
  });
});

describe("UX-8 — text meets 4.5:1 on every surface it can land on", () => {
  test.each(["ink-900", "ink-700", "ink-500"])(
    "%s carries normal-size copy",
    (name) => {
      for (const surface of SURFACES) {
        expect(
          ratio(token(name), token(surface)),
          `${name} on ${surface}`,
        ).toBeGreaterThanOrEqual(4.5);
      }
    },
  );

  test("ink-400 stays removed", () => {
    // It is not retunable: on this palette the darkest value clearing 4.5:1
    // against surface-muted is ink-500 itself, so a fourth muted step can only
    // exist by being illegible. Reintroducing the name should fail here rather
    // than quietly ship faint text again.
    expect(css).not.toMatch(/--color-ink-400\s*:/);
  });
});

describe("UX-9 — an interactive boundary meets 3:1 (WCAG 1.4.11)", () => {
  test("the control border is visible against every surface", () => {
    for (const surface of SURFACES) {
      expect(
        ratio(token("line-control"), token(surface)),
        `line-control on ${surface}`,
      ).toBeGreaterThanOrEqual(3);
    }
  });

  test("inputs use it, and not the decorative hairline", () => {
    const inputRule = css.match(/input,\s*select,\s*textarea\s*\{[^}]*\}/);
    expect(inputRule, "the input/select/textarea rule moved").not.toBeNull();
    expect(inputRule![0]).toContain("border-color: var(--color-line-control)");
  });

  test("the decorative hairlines are documented as too quiet to be a boundary", () => {
    // These two are deliberately below 3:1 — they are dividers and card edges,
    // which WCAG sets no ratio for. The test records that this is a decision,
    // so a future reader does not "fix" them into shouting.
    expect(ratio(token("line"), token("surface"))).toBeLessThan(3);
    expect(ratio(token("line-strong"), token("canvas"))).toBeLessThan(3);
  });
});

describe("filled controls", () => {
  test("canvas text on the brand fill stays readable", () => {
    expect(ratio(token("brand-600"), token("canvas"))).toBeGreaterThanOrEqual(4.5);
  });
});
