import type { components } from "./schema";
import { api } from "./client";
import type { ExportAsker } from "./dataExport";

/** A pending request to erase a child's data (`FE-4`: from the generated schema). */
export type ErasureRequest = components["schemas"]["ErasureRequestOut"];
export type ErasureRequestBody = components["schemas"]["ErasureRequestIn"];

const base = (asker: ExportAsker, studentId: number) =>
  asker === "tutor"
    ? `/api/v1/students/${studentId}/erasure`
    : `/api/v1/me/children/${studentId}/erasure`;

/** The pending request, or null when there is none. */
export const getErasure = (asker: ExportAsker, studentId: number) =>
  api<ErasureRequest | null>(base(asker, studentId));

export const requestErasure = (asker: ExportAsker, studentId: number, confirmName: string) =>
  api<ErasureRequest>(base(asker, studentId), {
    method: "POST",
    body: JSON.stringify({ confirm_name: confirmName } satisfies ErasureRequestBody),
  });

export const cancelErasure = (asker: ExportAsker, studentId: number) =>
  api<void>(base(asker, studentId), { method: "DELETE" });
