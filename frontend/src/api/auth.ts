import { api, storeTokens, type AuthResponse, type User } from "./client";
import { detectedTimezone } from "../lib/timezones";
import type { components } from "./schema";

export function login(identifier: string, password: string) {
  return api<AuthResponse>("/api/v1/auth/login", {
    method: "POST",
    body: JSON.stringify({ identifier, password }),
  });
}

/** Registration captures the browser's zone rather than asking for it: every
 * "today" the product shows is computed in the organization's zone, and a tutor
 * should not have to configure that before their first lesson list is correct.
 * The server validates it and falls back to UTC, so a wrong or missing answer
 * degrades rather than breaks.
 *
 * `detectedTimezone` is the one detector (lib/timezones) — the pickers offer
 * what it returns, so a browser it cannot read must produce the same "unset"
 * here as it does there. Two copies could disagree only by drifting. */
export function registerTutor(name: string, email: string, password: string) {
  return api<AuthResponse>("/api/v1/auth/register/tutor", {
    method: "POST",
    body: JSON.stringify({ name, email, password, timezone: detectedTimezone() }),
  });
}

export function fetchMe() {
  return api<User>("/api/v1/auth/me");
}

export type Organization = components["schemas"]["OrganizationOut"];

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

/** Any signed-in user, for themselves. Every other session ends; the reply is
 * this session's fresh access token (the refresh cookie rides alongside), which
 * must replace the stored one or the very next request is a 401. */
export async function changePassword(current_password: string, new_password: string) {
  const tokens = await api<{ access_token: string; token_type: string }>("/api/v1/auth/password", {
    method: "POST",
    body: JSON.stringify({ current_password, new_password }),
  });
  storeTokens(tokens);
  return tokens;
}
