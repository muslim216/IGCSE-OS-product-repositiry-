import { api } from "./client";
import type { components } from "./schema";

export interface Resource {
  id: number;
  group_id: number;
  kind: "file" | "recording";
  title: string;
  url: string | null;
  file_name: string | null;
  created_at: string;
}

export const listResources = (groupId: number, kind?: "file" | "recording") =>
  api<Resource[]>(`/api/v1/groups/${groupId}/resources${kind ? `?kind=${kind}` : ""}`);

/** A shared file or recording with the class it went to — what the Library lists
 *  across every one of the tutor's classes. */
export type LibraryResource = components["schemas"]["LibraryResourceOut"];

/** Mirrors `LIBRARY_RESOURCE_LIMIT` in backend/app/services/resource_library.py:
 *  the most rows `GET /resources` returns, so a list this long may be cut short. */
export const LIBRARY_RESOURCE_LIMIT = 200;

export const listMyResources = (kind?: "file" | "recording") =>
  api<LibraryResource[]>(`/api/v1/resources${kind ? `?kind=${kind}` : ""}`);

export function createFileResource(groupId: number, title: string, file: File) {
  const form = new FormData();
  form.append("kind", "file");
  form.append("title", title);
  form.append("file", file);
  return api<Resource>(`/api/v1/groups/${groupId}/resources`, { method: "POST", body: form });
}

export function createRecordingResource(groupId: number, title: string, url: string) {
  const form = new FormData();
  form.append("kind", "recording");
  form.append("title", title);
  form.append("url", url);
  return api<Resource>(`/api/v1/groups/${groupId}/resources`, { method: "POST", body: form });
}

export const deleteResource = (id: number) =>
  api<void>(`/api/v1/resources/${id}`, { method: "DELETE" });

export const resourceFilePath = (id: number) => `/api/v1/resources/${id}/file`;

export function isSafeHttpUrl(url: string | null | undefined): url is string {
  if (!url) return false;
  try {
    const scheme = new URL(url).protocol;
    return scheme === "http:" || scheme === "https:";
  } catch {
    return false;
  }
}
