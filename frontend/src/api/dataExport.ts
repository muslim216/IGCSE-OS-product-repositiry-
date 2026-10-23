import type { components } from "./schema";
import { api } from "./client";
import { fetchFileUrl } from "./homework";

/** Where a child's data export is up to (`FE-4`: from the generated schema). */
export type DataExport = components["schemas"]["DataExportOut"];

/** Who is asking: a tutor (or admin) reads through the student routes, a parent
 *  through their own child's. The server enforces who may; this only picks the path. */
export type ExportAsker = "tutor" | "parent";

const base = (asker: ExportAsker, studentId: number) =>
  asker === "tutor"
    ? `/api/v1/students/${studentId}/export`
    : `/api/v1/me/children/${studentId}/export`;

export const requestDataExport = (asker: ExportAsker, studentId: number) =>
  api<DataExport>(base(asker, studentId), { method: "POST" });

export const dataExportStatus = (asker: ExportAsker, studentId: number, exportId: number) =>
  api<DataExport>(`${base(asker, studentId)}/${exportId}`);

/** The ZIP as an object URL, fetched with the bearer token like any protected file. */
export const dataExportFileUrl = (asker: ExportAsker, studentId: number, exportId: number) =>
  fetchFileUrl(`${base(asker, studentId)}/${exportId}/file`);

/** An export is still being built. */
export const isBuilding = (e: DataExport | undefined) =>
  e?.status === "pending" || e?.status === "running";
