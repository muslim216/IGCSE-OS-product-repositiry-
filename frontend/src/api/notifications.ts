import type { components } from "./schema";
import { api } from "./client";

/**
 * Contact points, notification preferences and channel status (task 8.1).
 *
 * WhatsApp is the main channel and email the fallback. Nothing is ever sent to
 * an address until a tutor has seen it shown back and confirmed it.
 */
export type Contact = components["schemas"]["ContactOut"];
export type PersonContacts = components["schemas"]["PersonContactsOut"];
export type NotificationChannel = components["schemas"]["NotificationChannel"];
export type NotificationKind = components["schemas"]["NotificationKind"];
export type Preference = components["schemas"]["PreferenceItem"];
export type ChannelStatus = components["schemas"]["ChannelStatusOut"];
export type Undelivered = components["schemas"]["UndeliveredOut"];
export type OrganizationSettings = components["schemas"]["OrganizationSettingsUpdate"];

const json = (body: unknown) => JSON.stringify(body);

/** The learner and their linked parents, each with the addresses held for them. */
export const studentContacts = (studentId: number) =>
  api<PersonContacts[]>(`/api/v1/students/${studentId}/contacts`);

/** `userId` omitted means the learner; otherwise one of their parents. */
export const setStudentContact = (
  studentId: number,
  body: { channel: NotificationChannel; address: string; user_id?: number },
) => api<Contact>(`/api/v1/students/${studentId}/contacts`, { method: "PUT", body: json(body) });

export const confirmStudentContact = (studentId: number, contactId: number) =>
  api<Contact>(`/api/v1/students/${studentId}/contacts/${contactId}/confirm`, { method: "POST" });

export const myContacts = () => api<Contact[]>("/api/v1/me/contacts");

export const setMyContact = (body: { channel: NotificationChannel; address: string }) =>
  api<Contact>("/api/v1/me/contacts", { method: "PUT", body: json(body) });

export const confirmMyContact = (contactId: number) =>
  api<Contact>(`/api/v1/me/contacts/${contactId}/confirm`, { method: "POST" });

export const myPreferences = () => api<Preference[]>("/api/v1/me/notification-preferences");

export const setMyPreferences = (preferences: Preference[]) =>
  api<Preference[]>("/api/v1/me/notification-preferences", {
    method: "PUT",
    body: json({ preferences }),
  });

export const channelStatus = () => api<ChannelStatus>("/api/v1/notifications/status");

/** Messages from the last 30 days that reached nobody, newest first. */
export const undelivered = () => api<Undelivered[]>("/api/v1/notifications/undelivered");

export const setOrganizationSettings = (body: OrganizationSettings) =>
  api<components["schemas"]["OrganizationOut"]>("/api/v1/me/organization", {
    method: "PUT",
    body: json(body),
  });
