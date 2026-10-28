import { api, upload, type UploadOptions } from "./client";
import type { components } from "./schema";

/** Aliased from the generated schema rather than hand-mirrored (`FE-4`). */
export type Mock = components["schemas"]["MockOut"];
export type MockDetail = components["schemas"]["MockDetail"];
export type MockClock = components["schemas"]["MockClockOut"];
export type MockSubmission = components["schemas"]["MockSubmissionOut"];

export const myMocks = () => api<Mock[]>("/api/v1/mocks/mine");

export const getMock = (id: number) => api<MockDetail>(`/api/v1/mocks/${id}`);

/** Starts this student's clock, or returns the one already running.
 *
 *  Idempotent on the server, but calling it is still the act that writes the
 *  start time on a first open — the page must fire it once per mock, never on
 *  every render (`AV-116`). */
export const openMock = (id: number) =>
  api<MockClock>(`/api/v1/mocks/${id}/open`, { method: "POST" });

export function sitMock(mockId: number, files: File[], typedAnswer = "", opts?: UploadOptions) {
  const form = new FormData();
  for (const f of files) form.append("files", f);
  if (typedAnswer.trim()) form.append("typed_answer", typedAnswer);
  return upload<MockSubmission>(`/api/v1/mocks/${mockId}/submissions`, form, opts);
}

export const myMockSubmission = (mockId: number) =>
  api<MockSubmission | null>(`/api/v1/mocks/${mockId}/my-submission`);

/** Only the question paper. There is no student-readable mark scheme route —
 *  handing one over would defeat the exercise. */
export const mockPaperPath = (id: number) => `/api/v1/mocks/${id}/paper`;

/* ---- The tutor's side: upload a mock for the AI to read and mark ---------- */

/** One student of the mock's class. Marks are final marks only, null until then. */
export type MockResult = components["schemas"]["MockResultRow"];

export const listMocks = () => api<Mock[]>("/api/v1/mocks");

/** `group_id` is deliberately not offered: a mock reaches students only when
 *  the tutor opens it to a class after checking what the AI read
 *  (`setMockClass`). */
export function uploadMock(payload: {
  subject_id: number;
  title: string;
  paper: File;
  /** Optional. Without it nothing auto-finalizes: every mark waits for the tutor. */
  mark_scheme?: File | null;
  duration_minutes?: number | null;
  sat_on?: string | null;
}) {
  const form = new FormData();
  form.append("subject_id", String(payload.subject_id));
  form.append("title", payload.title);
  form.append("paper", payload.paper);
  if (payload.mark_scheme) form.append("mark_scheme", payload.mark_scheme);
  if (payload.duration_minutes) form.append("duration_minutes", String(payload.duration_minutes));
  if (payload.sat_on) form.append("sat_on", payload.sat_on);
  return api<Mock>("/api/v1/mocks", { method: "POST", body: form });
}

/** Reads a mock the AI couldn't read once more. Refused (409) unless it failed. */
export const retryMock = (id: number) =>
  api<Mock>(`/api/v1/mocks/${id}/retry-extraction`, { method: "POST" });

/** Opens the mock to a class. Refused (409) once anyone has started it. */
export const setMockClass = (id: number, groupId: number) =>
  api<Mock>(`/api/v1/mocks/${id}`, {
    method: "PATCH",
    body: JSON.stringify({ group_id: groupId }),
  });

export const mockResults = (id: number) => api<MockResult[]>(`/api/v1/mocks/${id}/results`);

export const mockMarkSchemePath = (id: number) => `/api/v1/mocks/${id}/mark-scheme`;
