import type { components } from "./schema";
import { api } from "./client";

/** An adult who can read a child's record. `id` is the link's, which removing it takes. */
export type LinkedParent = components["schemas"]["LinkedParentOut"];

/** A tutor's view of who is linked to a student they teach. */
export const studentParents = (studentId: number) =>
  api<LinkedParent[]>(`/api/v1/students/${studentId}/parents`);

export const removeStudentParent = (studentId: number, linkId: number) =>
  api<void>(`/api/v1/students/${studentId}/parents/${linkId}`, { method: "DELETE" });

/** The student's own view and removal. */
export const myParentLinks = () => api<LinkedParent[]>("/api/v1/me/parent-links");

export const removeMyParentLink = (linkId: number) =>
  api<void>(`/api/v1/me/parent-links/${linkId}`, { method: "DELETE" });

/** A parent ends their own access to a child. */
export const stopFollowingChild = (studentId: number) =>
  api<void>(`/api/v1/me/children/${studentId}`, { method: "DELETE" });
