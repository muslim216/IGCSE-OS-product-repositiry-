import { api, type AuthResponse, type User } from "./client";

export function login(identifier: string, password: string) {
  return api<AuthResponse>("/api/v1/auth/login", {
    method: "POST",
    body: JSON.stringify({ identifier, password }),
  });
}

/** The browser's IANA zone, or null if it cannot report one.
 *
 * Captured here rather than asked for: every "today" the product shows is
 * computed in the organization's zone, and a tutor should not have to
 * configure that before their first lesson list is correct. The server
 * validates it and falls back to UTC, so a wrong or missing answer degrades
 * rather than breaks. */
function browserTimezone(): string | null {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || null;
  } catch {
    return null;
  }
}

export function registerTutor(name: string, email: string, password: string) {
  return api<AuthResponse>("/api/v1/auth/register/tutor", {
    method: "POST",
    body: JSON.stringify({ name, email, password, timezone: browserTimezone() }),
  });
}

export function fetchMe() {
  return api<User>("/api/v1/auth/me");
}

export interface Organization {
  id: number;
  name: string;
  /** null means no zone is stored and the server is answering in UTC. */
  timezone: string | null;
}

export const myOrganization = () => api<Organization>("/api/v1/me/organization");

export const setOrganizationTimezone = (timezone: string | null) =>
  api<Organization>("/api/v1/me/organization/timezone", {
    method: "PUT",
    body: JSON.stringify({ timezone }),
  });

/** The caller's own zone override (null = follow the organization's). */
export const myTimezone = () => api<User>("/api/v1/me/timezone");

export const setMyTimezone = (timezone: string | null) =>
  api<User>("/api/v1/me/timezone", {
    method: "PUT",
    body: JSON.stringify({ timezone }),
  });

export function logout() {
  return api<void>("/api/v1/auth/logout", { method: "POST" });
}
