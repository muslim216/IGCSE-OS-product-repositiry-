import { api, type AuthResponse, type User } from "./client";

export function login(identifier: string, password: string) {
  return api<AuthResponse>("/api/v1/auth/login", {
    method: "POST",
    body: JSON.stringify({ identifier, password }),
  });
}

export function registerTutor(name: string, email: string, password: string) {
  return api<AuthResponse>("/api/v1/auth/register/tutor", {
    method: "POST",
    body: JSON.stringify({ name, email, password }),
  });
}

export function fetchMe() {
  return api<User>("/api/v1/auth/me");
}
