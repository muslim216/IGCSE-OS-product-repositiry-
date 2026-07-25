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

/**
 * What we keep in localStorage. Deliberately NOT the refresh token.
 *
 * The server also sets the refresh token as an httpOnly, SameSite=Lax cookie
 * scoped to /api/v1/auth, which script on this page cannot read. Persisting a
 * copy here would throw that away: any XSS would walk off with a 30-day
 * credential instead of an access token that expires in 30 minutes.
 *
 * The access token still lives in localStorage because it has to be readable
 * to go in the Authorization header. Keeping it short-lived is what limits the
 * damage; `refreshTokens()` below relies on the cookie alone.
 */
export interface StoredTokens {
  access_token: string;
  token_type: string;
}

const STORAGE_KEY = "igcse-os-tokens";

// Optional escape hatch for deployments without a same-origin API proxy
// (e.g. a Vercel preview without vercel.json applied yet).
export const API_BASE: string = import.meta.env.VITE_API_BASE_URL ?? "";

export function apiUrl(path: string): string {
  return `${API_BASE}${path}`;
}

export function getStoredTokens(): StoredTokens | null {
  const raw = localStorage.getItem(STORAGE_KEY);
  if (!raw) return null;
  const parsed = JSON.parse(raw) as Partial<TokenPair>;
  if (!parsed.access_token) return null;
  return {
    access_token: parsed.access_token,
    token_type: parsed.token_type ?? "bearer",
  };
}

export function storeTokens(tokens: TokenPair | StoredTokens | null) {
  if (tokens) {
    // Persist the access token only — never `refresh_token`, even though the
    // server hands us one. Callers pass the whole pair straight from a login
    // response, so the narrowing happens here rather than at every call site.
    const stored: StoredTokens = {
      access_token: tokens.access_token,
      token_type: tokens.token_type,
    };
    localStorage.setItem(STORAGE_KEY, JSON.stringify(stored));
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

export async function refreshTokens(): Promise<StoredTokens | null> {
  // Empty body on purpose: the refresh token travels as the httpOnly cookie
  // the server set at login, which `credentials: "include"` attaches and this
  // script cannot read. That requires the API to be same-origin — both
  // supported deploys proxy /api/* to the backend (render.yaml routes,
  // frontend/vercel.json rewrites). A cross-origin VITE_API_BASE_URL build
  // will not carry a SameSite=Lax cookie, so sessions there end at the access
  // token's expiry instead of refreshing.
  const resp = await fetch(apiUrl("/api/v1/auth/refresh"), {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({}),
  });
  if (!resp.ok) {
    storeTokens(null);
    return null;
  }
  const fresh = (await resp.json()) as TokenPair;
  storeTokens(fresh);
  return getStoredTokens();
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
  const resp = await fetch(apiUrl(path), { ...options, headers, credentials: "include" });

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
