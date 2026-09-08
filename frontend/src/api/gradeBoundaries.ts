import { api } from "./client";
import type { components } from "./schema";

// FE-4: aliases of the generated schema, never hand-written interfaces. The
// third source, "subject", went with the global Subject.grade_boundaries column
// in task 2.4 — `source` is now "organization" (this org's own numbers, and what
// every predicted grade is mapped through) or "none" (nothing set, so there is
// no predicted grade for this subject and the list below is an unconfirmed
// published starting point that must be labelled as such).
export type GradeBand = components["schemas"]["GradeBand"];
export type GradeBoundaries = components["schemas"]["GradeBoundariesOut"];

export const getGradeBoundaries = (subjectId: number) =>
  api<GradeBoundaries>(`/api/v1/subjects/${subjectId}/grade-boundaries`);

export const saveGradeBoundaries = (subjectId: number, boundaries: GradeBand[]) =>
  api<GradeBoundaries>(`/api/v1/subjects/${subjectId}/grade-boundaries`, {
    method: "PUT",
    body: JSON.stringify({ boundaries }),
  });
