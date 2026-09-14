import { api } from "./client";
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

export function sitMock(mockId: number, files: File[], typedAnswer = "") {
  const form = new FormData();
  for (const f of files) form.append("files", f);
  if (typedAnswer.trim()) form.append("typed_answer", typedAnswer);
  return api<MockSubmission>(`/api/v1/mocks/${mockId}/submissions`, { method: "POST", body: form });
}

export const myMockSubmission = (mockId: number) =>
  api<MockSubmission | null>(`/api/v1/mocks/${mockId}/my-submission`);

/** Only the question paper. There is no student-readable mark scheme route —
 *  handing one over would defeat the exercise. */
export const mockPaperPath = (id: number) => `/api/v1/mocks/${id}/paper`;
