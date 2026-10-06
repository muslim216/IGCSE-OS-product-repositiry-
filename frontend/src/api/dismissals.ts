import { api } from "./client";
import type { components } from "./schema";

/** What the tutor has hidden with "Not now". The keys are opaque labels this
 *  client chose; the server stores them and checks only their shape. */
export type DismissalsOut = components["schemas"]["DismissalsOut"];

const one = (key: string) => `/api/v1/me/dismissals/${encodeURIComponent(key)}`;

export const listDismissals = () => api<DismissalsOut>("/api/v1/me/dismissals");
export const dismissPrompt = (key: string) => api<void>(one(key), { method: "PUT" });
export const restoreAllPrompts = () => api<void>("/api/v1/me/dismissals", { method: "DELETE" });
