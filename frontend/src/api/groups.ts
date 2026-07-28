import { api, type AuthResponse, type User } from "./client";

export interface Subject {
  id: number;
  exam_board: string;
  code: string;
  name: string;
  grade_scale: string;
}

export interface NextLesson {
  weekday: number;
  start_time: string;
  duration_min: number;
  title: string | null;
}

/** The at-a-glance counts a class card shows. */
export interface GroupSummary {
  member_count: number;
  published_assignment_count: number;
  awaiting_review_count: number;
  next_lesson: NextLesson | null;
}

export interface Group extends GroupSummary {
  id: number;
  name: string;
  subject: Subject;
}

export interface GroupDetail extends GroupSummary {
  id: number;
  name: string;
  subject: Subject;
  members: User[];
}

export interface Invite {
  code: string;
  kind: string;
  expires_at: string | null;
}

export interface InvitePreview {
  kind: "student_join" | "parent_link";
  group_name: string | null;
  subject_name: string | null;
  tutor_name: string | null;
  student_name: string | null;
}

export interface Lesson {
  id: number;
  group_id: number;
  weekday: number;
  start_time: string;
  duration_min: number;
  title: string | null;
}

export interface UpcomingLesson {
  group_id: number;
  group_name: string;
  subject_name: string;
  weekday: number;
  start_time: string;
  duration_min: number;
  title: string | null;
}

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
export const deleteGroup = (id: number) =>
  api<void>(`/api/v1/groups/${id}`, { method: "DELETE" });

export const createInvite = (groupId: number) =>
  api<Invite>(`/api/v1/groups/${groupId}/invites`, { method: "POST" });
export const previewInvite = (code: string) =>
  api<InvitePreview>(`/api/v1/auth/invites/${code}`);
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

export const listLessons = (groupId: number) =>
  api<Lesson[]>(`/api/v1/groups/${groupId}/lessons`);
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
