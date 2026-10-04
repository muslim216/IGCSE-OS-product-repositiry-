import type { components } from "../api/schema";

type MistakeSource = components["schemas"]["MistakeRow"]["source"];

/**
 * Who decided a mistake tag, in words a tutor can trust. Exhaustive on purpose:
 * a new source added on the backend fails the type check here instead of
 * falling through to "Tagged by AI" (PROD-1). `demo` rows are seeded example
 * data, never a model's call, so they must not claim to be one.
 */
export function mistakeSourceLabel(source: MistakeSource): string {
  switch (source) {
    case "tutor":
      return "Your call";
    case "demo":
      return "Example data";
    case "ai":
      return "Tagged by AI";
  }
}
