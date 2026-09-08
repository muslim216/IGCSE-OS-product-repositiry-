import { api } from "./client";
import type { components } from "./schema";

/** The per-subject marking rules — Library's "AI marking agreement"
 *  (`AV-75`, `AV-111`). They describe **how** the AI marks, never **when a mark
 *  counts**: nothing here reaches auto-finalization (`AV-25`). */
export type MarkingRules = components["schemas"]["MarkingRulesOut"];

/** Mirrors `MAX_MARKING_RULES` in backend/app/schemas/marking_rules.py, which
 *  is the control — this one is so the tutor sees the limit while typing rather
 *  than as a rejected save. */
export const MAX_MARKING_RULES = 8000;

export const getMarkingRules = (subjectId: number) =>
  api<MarkingRules>(`/api/v1/subjects/${subjectId}/marking-rules`);

export const saveMarkingRules = (subjectId: number, rules: string) =>
  api<MarkingRules>(`/api/v1/subjects/${subjectId}/marking-rules`, {
    method: "PUT",
    body: JSON.stringify({ rules }),
  });
