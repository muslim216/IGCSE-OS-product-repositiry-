import { api } from "./client";
import type { components } from "./schema";

/** Zoom / Google Meet attendance (task 7.3). Types alias the server's schemas (FE-4). */
export type IntegrationStatus = components["schemas"]["IntegrationStatusOut"];
export type MeetingProvider = IntegrationStatus["provider"];
export type LessonMeeting = components["schemas"]["LessonMeetingOut"];
export type MeetingParticipant = components["schemas"]["MeetingParticipantOut"];
export type MeetingImport = components["schemas"]["MeetingImportOut"];

export const PROVIDER_LABEL: Record<MeetingProvider, string> = {
  zoom: "Zoom",
  google_meet: "Google Meet",
};

export const listIntegrations = () => api<IntegrationStatus[]>("/api/v1/integrations");

export const getAuthorizeUrl = (provider: MeetingProvider) =>
  api<components["schemas"]["IntegrationAuthUrlOut"]>(
    `/api/v1/integrations/${provider}/authorize-url`,
  );

/** The provider sends the browser back to a page of ours, which hands the code
 *  here under the tutor's own session. The server verifies `state`. */
export const completeIntegration = (provider: MeetingProvider, code: string, state: string) =>
  api<IntegrationStatus>(
    `/api/v1/integrations/${provider}/callback?${new URLSearchParams({ code, state })}`,
  );

export const disconnectIntegration = (provider: MeetingProvider) =>
  api<void>(`/api/v1/integrations/${provider}`, { method: "DELETE" });

export const getLessonMeeting = (lessonId: number) =>
  api<LessonMeeting>(`/api/v1/lessons/${lessonId}/meeting`);

export const importAttendance = (lessonId: number) =>
  api<MeetingImport>(`/api/v1/lessons/${lessonId}/attendance/import`, { method: "POST" });

export const resolveParticipant = (lessonId: number, participantId: number, studentId: number) =>
  api<MeetingParticipant>(`/api/v1/lessons/${lessonId}/participants/${participantId}/resolve`, {
    method: "POST",
    body: JSON.stringify({ student_id: studentId }),
  });

/** `null` clears the link. */
export const setMeetingLink = (lessonId: number, meetingLink: string | null) =>
  api<components["schemas"]["LessonOut"]>(`/api/v1/lessons/${lessonId}`, {
    method: "PATCH",
    body: JSON.stringify({ meeting_link: meetingLink }),
  });
