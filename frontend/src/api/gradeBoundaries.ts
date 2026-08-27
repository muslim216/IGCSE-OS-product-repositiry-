import type { components } from "./schema";
import { api } from "./client";

/** Mirrors backend/app/schemas/grade_boundaries.py. */
export type GradeBand = components["schemas"]["GradeBand"];

/** `source` is a plain `str` in the OpenAPI schema; the three-value union is a
    frontend refinement of it (a surface branches on the exact value), so it is
    kept here while the rest of the shape is anchored to the generated type. */
export type GradeBoundaries = Omit<components["schemas"]["GradeBoundariesOut"], "source"> & {
  /** "organization" — this tutor's own numbers; "subject" — the global default
      shipped with the syllabus; "none" — nothing set, and the list below is an
      unconfirmed published starting point that must be labelled as such. */
  source: "organization" | "subject" | "none";
};

export const getGradeBoundaries = (subjectId: number) =>
  api<GradeBoundaries>(`/api/v1/subjects/${subjectId}/grade-boundaries`);

export const saveGradeBoundaries = (subjectId: number, boundaries: GradeBand[]) =>
  api<GradeBoundaries>(`/api/v1/subjects/${subjectId}/grade-boundaries`, {
    method: "PUT",
    body: JSON.stringify({ boundaries }),
  });
