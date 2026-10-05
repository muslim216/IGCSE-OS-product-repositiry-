import type { Contact, NotificationChannel, NotificationKind } from "../api/notifications";

export const CHANNEL_LABEL: Record<NotificationChannel, string> = {
  whatsapp: "WhatsApp",
  email: "Email",
};

/** What each kind of message is, in the reader's words. */
export const KIND_LABEL: Record<NotificationKind, string> = {
  weekly_send: "The weekly summary",
  homework_set: "New homework",
  homework_due: "Homework due soon",
  marked_work_ready: "Marked work is ready",
  lesson_reminder: "Lesson reminders",
  review_queue: "Work waiting for review",
  invite: "Invitations",
  contact_confirm: "Contact confirmation",
};

/** The kinds each role is ever sent, so nobody is offered a switch for a
 *  message they could never receive. */
export const KINDS_FOR_ROLE: Record<string, NotificationKind[]> = {
  tutor: ["weekly_send", "lesson_reminder", "review_queue"],
  admin: ["weekly_send", "lesson_reminder", "review_queue"],
  student: ["weekly_send", "homework_set", "homework_due", "marked_work_ready", "lesson_reminder"],
  parent: ["weekly_send", "homework_set", "marked_work_ready"],
};

const SUPPRESSED_LABEL: Record<string, string> = {
  opted_out: "Opted out — they asked us to stop",
  bounced: "Not delivering — the address bounced",
  complaint: "Not delivering — marked as unwanted",
  provider_rejected: "Not delivering — WhatsApp can't reach this number",
};

export type ContactState = "none" | "unconfirmed" | "suppressed" | "ready";

export function contactState(contact: Contact | undefined): ContactState {
  if (!contact) return "none";
  if (contact.suppressed_at) return "suppressed";
  return contact.confirmed_at ? "ready" : "unconfirmed";
}

export function suppressedLabel(contact: Contact): string {
  return SUPPRESSED_LABEL[contact.suppressed_reason ?? ""] ?? "Not delivering";
}

/** Why a message reached nobody, in plain words. */
export const UNDELIVERED_LABEL: Record<string, string> = {
  failed: "Could not be delivered",
  suppressed: "They opted out or switched this off",
  no_channel: "No confirmed number or email",
  channel_unconfigured: "WhatsApp and email aren't connected yet",
};
