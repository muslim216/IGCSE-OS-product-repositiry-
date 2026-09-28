import { api } from "./client";
import type { components } from "./schema";

// FE-4: aliases of the generated schema, never hand-written interfaces.
// Tutor-defined criteria (task 5.4b). Shown beside readiness, never in it, and
// every score carries `source: "tutor"` — the UI labels it "Tutor-entered".
export type CustomCriterion = components["schemas"]["CustomCriterionOut"];
export type CustomCriterionCreate = components["schemas"]["CustomCriterionCreate"];
export type CustomCriterionUpdate = components["schemas"]["CustomCriterionUpdate"];
export type StudentCriterionScore = components["schemas"]["StudentCriterionScoreOut"];

const BASE = "/api/v1/custom-criteria";
const scoresPath = (studentId: number) => `/api/v1/students/${studentId}/custom-criteria`;

export const listCustomCriteria = (includeArchived = false) =>
  api<CustomCriterion[]>(includeArchived ? `${BASE}?include_archived=true` : BASE);

export const createCustomCriterion = (body: CustomCriterionCreate) =>
  api<CustomCriterion>(BASE, { method: "POST", body: JSON.stringify(body) });

export const updateCustomCriterion = (id: number, body: CustomCriterionUpdate) =>
  api<CustomCriterion>(`${BASE}/${id}`, { method: "PATCH", body: JSON.stringify(body) });

export const getStudentCriteria = (studentId: number) =>
  api<StudentCriterionScore[]>(scoresPath(studentId));

export const setCriterionScore = (studentId: number, criterionId: number, score: number) =>
  api<StudentCriterionScore>(`${scoresPath(studentId)}/${criterionId}`, {
    method: "PUT",
    body: JSON.stringify({ score }),
  });

export const clearCriterionScore = (studentId: number, criterionId: number) =>
  api<void>(`${scoresPath(studentId)}/${criterionId}`, { method: "DELETE" });
