import { api } from "./client";
import type { components } from "./schema";

/** The second per-subject setup document (task 2.5, `AV-10`): the scheme of
 *  work Phase 6 reads to weight the teaching plan. Tutor material — every route
 *  behind it is tutor-gated server-side (`AV-95`). */
export type TeachingGuidance = components["schemas"]["TeachingGuidanceOut"];

export const getTeachingGuidance = (subjectId: number) =>
  api<TeachingGuidance>(`/api/v1/subjects/${subjectId}/teaching-guidance`);

export function uploadTeachingGuidance(subjectId: number, file: File) {
  const form = new FormData();
  form.append("file", file);
  return api<TeachingGuidance>(`/api/v1/subjects/${subjectId}/teaching-guidance`, {
    method: "PUT",
    body: form,
  });
}

export const deleteTeachingGuidance = (subjectId: number) =>
  api<TeachingGuidance>(`/api/v1/subjects/${subjectId}/teaching-guidance`, { method: "DELETE" });

/** For `AuthFileLink` — the download carries the bearer token and may redirect
 *  to a signed object-store URL, so it never goes through a plain `<a href>`. */
export const teachingGuidanceFilePath = (subjectId: number) =>
  `/api/v1/subjects/${subjectId}/teaching-guidance/file`;
