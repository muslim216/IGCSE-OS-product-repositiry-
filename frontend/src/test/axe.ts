import axe from "axe-core";

/* Rules jsdom cannot judge: it has no layout or painted colours, so
   colour-contrast cannot be computed (it is checked by eye against the design
   tokens instead). Everything else stays on. */
const JSDOM_CANNOT_EVALUATE = ["color-contrast"];

/** Runs axe on a rendered element and returns a readable list of violations. */
export async function axeViolations(element: Element, disabled: string[] = []): Promise<string[]> {
  const rules = Object.fromEntries(
    [...JSDOM_CANNOT_EVALUATE, ...disabled].map((id) => [id, { enabled: false }]),
  );
  const results = await axe.run(element, { rules });
  return results.violations.map(
    (v) => `${v.id}: ${v.help} (${v.nodes.map((n) => n.target.join(" ")).join(" | ")})`,
  );
}
