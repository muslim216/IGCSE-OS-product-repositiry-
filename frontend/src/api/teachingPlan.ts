import { api } from "./client";
import type { components } from "./schema";

/** Teaching-plan inputs on a class (task 6.2, `AV-15`). Tutor-only server-side
 *  (`AV-19`): a plan and its exam date are never shown to students or parents. */
export type PlanOverview = components["schemas"]["PlanOverview"];
export type PlanInputs = components["schemas"]["PlanInputsOut"];
export type PlanInputsBody = components["schemas"]["PlanInputsIn"];
export type PlanBreak = components["schemas"]["PlanBreakOut"];
export type PlanBreakBody = components["schemas"]["PlanBreakCreate"];

const base = (groupId: number) => `/api/v1/groups/${groupId}/plan`;

export const getPlan = (groupId: number) => api<PlanOverview>(base(groupId));

export const savePlanInputs = (groupId: number, body: PlanInputsBody) =>
  api<PlanOverview>(`${base(groupId)}/inputs`, { method: "PUT", body: JSON.stringify(body) });

export const addPlanBreak = (groupId: number, body: PlanBreakBody) =>
  api<PlanBreak>(`${base(groupId)}/breaks`, { method: "POST", body: JSON.stringify(body) });

export const deletePlanBreak = (groupId: number, breakId: number) =>
  api<void>(`${base(groupId)}/breaks/${breakId}`, { method: "DELETE" });
