export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

export interface User {
  id: number;
  email: string | null;
  username: string | null;
  role: "student" | "tutor" | "parent" | "admin";
  name: string;
}

export interface AuthResponse {
  user: User;
  tokens: TokenPair;
}

const STORAGE_KEY = "igcse-os-tokens";

export function getStoredTokens(): TokenPair | null {
  const raw = localStorage.getItem(STORAGE_KEY);
  return raw ? (JSON.parse(raw) as TokenPair) : null;
}

export function storeTokens(tokens: TokenPair | null) {
  if (tokens) {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(tokens));
  } else {
    localStorage.removeItem(STORAGE_KEY);
  }
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function refreshTokens(): Promise<TokenPair | null> {
  const tokens = getStoredTokens();
  if (!tokens) return null;
  const resp = await fetch("/api/v1/auth/refresh", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: tokens.refresh_token }),
  });
  if (!resp.ok) {
    storeTokens(null);
    return null;
  }
  const fresh = (await resp.json()) as TokenPair;
  storeTokens(fresh);
  return fresh;
}

export async function api<T>(
  path: string,
  options: RequestInit = {},
  retry = true,
): Promise<T> {
  const tokens = getStoredTokens();
  const headers = new Headers(options.headers);
  if (!(options.body instanceof FormData) && options.body !== undefined) {
    headers.set("Content-Type", "application/json");
  }
  if (tokens) {
    headers.set("Authorization", `Bearer ${tokens.access_token}`);
  }
  const resp = await fetch(path, { ...options, headers });

  if (resp.status === 401 && tokens && retry) {
    const fresh = await refreshTokens();
    if (fresh) return api<T>(path, options, false);
  }
  if (!resp.ok) {
    let detail = resp.statusText;
    try {
      const body = await resp.json();
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      // non-JSON error body
    }
    throw new ApiError(resp.status, detail);
  }
  if (resp.status === 204) return undefined as T;
  return (await resp.json()) as T;
}
