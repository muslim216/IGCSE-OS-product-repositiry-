import { api } from "./client";

/** Mirrors backend/app/schemas/grade_boundaries.py. */
export interface GradeBand {
  grade: string;
  /** The lowest percentage that earns this grade. */
  min: number;
}

export interface GradeBoundaries {
  subject_id: number;
  subject_name: string;
  grade_scale: string;
  /** "organization" — this tutor's own numbers; "subject" — the global default
      shipped with the syllabus; "none" — nothing set, and the list below is an
      unconfirmed published starting point that must be labelled as such. */
  source: "organization" | "subject" | "none";
  boundaries: GradeBand[];
}

export const getGradeBoundaries = (subjectId: number) =>
  api<GradeBoundaries>(`/api/v1/subjects/${subjectId}/grade-boundaries`);

export const saveGradeBoundaries = (subjectId: number, boundaries: GradeBand[]) =>
  api<GradeBoundaries>(`/api/v1/subjects/${subjectId}/grade-boundaries`, {
    method: "PUT",
    body: JSON.stringify({ boundaries }),
  });
