import { api, type AuthResponse, type User } from "./client";
import type { components } from "./schema";

export type Subject = components["schemas"]["SubjectOut"];

export type NextLesson = components["schemas"]["NextLesson"];

/** The aggregates a class card shows at a glance — the summary fields of
    `GroupOut` without its identity. `students_with_evidence` is a coverage
    numerator over `member_count`: enrolled students with confident evidence in
    this class's subject. `0` is a real answer, not a missing one — a status
    drawn from part of a class must not look like one drawn from all of it. */
export type GroupSummary = Omit<components["schemas"]["GroupOut"], "id" | "name" | "subject">;

export type Group = components["schemas"]["GroupOut"];

export type GroupDetail = components["schemas"]["GroupDetail"];

export type Invite = components["schemas"]["InviteOut"];

/** `kind` is a plain `str` in the OpenAPI schema; the two-value union is a
    frontend refinement (a surface branches on the exact value), kept here while
    the rest of the shape is anchored to the generated type. */
export type InvitePreview = Omit<components["schemas"]["InvitePreview"], "kind"> & {
  kind: "student_join" | "parent_link";
};

/** A recurring schedule slot for a class (weekday + start time), not a single
    lesson occurrence — the backend calls this a ScheduleSlot. */
export type Lesson = components["schemas"]["ScheduleSlotOut"];

export type UpcomingLesson = components["schemas"]["UpcomingScheduleSlot"];

export const WEEKDAYS = [
  "Monday",
  "Tuesday",
  "Wednesday",
  "Thursday",
  "Friday",
  "Saturday",
  "Sunday",
];

export const listSubjects = () => api<Subject[]>("/api/v1/subjects");
export const listGroups = () => api<Group[]>("/api/v1/groups");
export const getGroup = (id: number) => api<GroupDetail>(`/api/v1/groups/${id}`);
export const createGroup = (name: string, subject_id: number) =>
  api<Group>("/api/v1/groups", { method: "POST", body: JSON.stringify({ name, subject_id }) });
export const deleteGroup = (id: number) => api<void>(`/api/v1/groups/${id}`, { method: "DELETE" });

export const createInvite = (groupId: number) =>
  api<Invite>(`/api/v1/groups/${groupId}/invites`, { method: "POST" });
export const previewInvite = (code: string) => api<InvitePreview>(`/api/v1/auth/invites/${code}`);
export const joinWithInvite = (invite_code: string) =>
  api<void>("/api/v1/auth/join", { method: "POST", body: JSON.stringify({ invite_code }) });

export const registerStudent = (payload: {
  invite_code: string;
  name: string;
  email: string;
  password: string;
}) =>
  api<AuthResponse>("/api/v1/auth/register/student", {
    method: "POST",
    body: JSON.stringify(payload),
  });

export const registerParent = (payload: {
  link_code: string;
  name: string;
  email: string;
  password: string;
}) =>
  api<AuthResponse>("/api/v1/auth/register/parent", {
    method: "POST",
    body: JSON.stringify(payload),
  });

export const createStudentAccount = (
  groupId: number,
  payload: { name: string; username: string; password: string },
) =>
  api<User>(`/api/v1/groups/${groupId}/students`, {
    method: "POST",
    body: JSON.stringify(payload),
  });

export const removeMember = (groupId: number, studentId: number) =>
  api<void>(`/api/v1/groups/${groupId}/members/${studentId}`, { method: "DELETE" });

export const resetStudentPassword = (groupId: number, studentId: number, password: string) =>
  api<void>(`/api/v1/groups/${groupId}/students/${studentId}/reset-password`, {
    method: "POST",
    body: JSON.stringify({ password }),
  });

export const createParentCode = (studentId: number) =>
  api<Invite>(`/api/v1/students/${studentId}/parent-code`, { method: "POST" });

export const listLessons = (groupId: number) => api<Lesson[]>(`/api/v1/groups/${groupId}/lessons`);
export const createLesson = (
  groupId: number,
  payload: { weekday: number; start_time: string; duration_min: number; title: string | null },
) =>
  api<Lesson>(`/api/v1/groups/${groupId}/lessons`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
export const deleteLesson = (groupId: number, lessonId: number) =>
  api<void>(`/api/v1/groups/${groupId}/lessons/${lessonId}`, { method: "DELETE" });

export const myGroups = () => api<Group[]>("/api/v1/me/groups");
export const myLessons = () => api<UpcomingLesson[]>("/api/v1/me/lessons");
export const myChildren = () => api<User[]>("/api/v1/me/children");
export const myTodayLessons = () => api<UpcomingLesson[]>("/api/v1/me/today-lessons");

export const generateClassBrief = (groupId: number) =>
  api<{ brief: string }>(`/api/v1/groups/${groupId}/brief`, { method: "POST" });
