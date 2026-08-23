export interface TokenPair {
  access_token: string;
  token_type: string;
}

export interface User {
  id: number;
  email: string | null;
  username: string | null;
  role: "student" | "tutor" | "parent" | "admin";
  name: string;
  /** The user's own IANA zone, or null to follow the organization's. */
  time_zone: string | null;
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

const STORAGE_KEY = "avora-tokens";

// Optional escape hatch for deployments without a same-origin API proxy
// (e.g. a Vercel preview without vercel.json applied yet).
export const API_BASE: string = import.meta.env.VITE_API_BASE_URL ?? "";

export function apiUrl(path: string): string {
  return `${API_BASE}${path}`;
}

export function getStoredTokens(): StoredTokens | null {
  const raw = localStorage.getItem(STORAGE_KEY);
  if (!raw) return null;
  // Every request reads this, so anything unparseable here would throw before
  // the fetch and take down the whole app — including the login that would
  // replace the bad entry. Discard it and let the user sign in again instead.
  let parsed: Partial<TokenPair>;
  try {
    parsed = JSON.parse(raw) as Partial<TokenPair>;
  } catch {
    localStorage.removeItem(STORAGE_KEY);
    return null;
  }
  if (typeof parsed.access_token !== "string" || !parsed.access_token) {
    localStorage.removeItem(STORAGE_KEY);
    return null;
  }
  return {
    access_token: parsed.access_token,
    token_type: typeof parsed.token_type === "string" ? parsed.token_type : "bearer",
  };
}

export function storeTokens(tokens: TokenPair | StoredTokens | null) {
  if (tokens) {
    // Narrows to just what we persist. The server never sends a refresh
    // token in a response body at all now — TokenPair itself carries only
    // the access token — so this is belt-and-braces against a caller that
    // widens the type later, not a defense against the current contract.
    const stored: StoredTokens = {
      access_token: tokens.access_token,
      token_type: tokens.token_type,
    };
    localStorage.setItem(STORAGE_KEY, JSON.stringify(stored));
  } else {
    localStorage.removeItem(STORAGE_KEY);
  }
}

/** One field-level complaint, unpacked from FastAPI's 422 body. */
export interface FieldError {
  /** Dotted path as the server named it — `email`, `questions.0.max_marks`. */
  path: string;
  /** Humanised label for that path — `Email`, `Questions #1 → Max marks`. */
  label: string;
  /** The server's own wording — `Field required`. */
  message: string;
}

export class ApiError extends Error {
  status: number;
  /**
   * Populated only for a 422 carrying FastAPI's validation list. A form can
   * render these against the offending inputs; `message` already contains the
   * same information joined into one sentence, so a caller that only shows
   * `err.message` needs no change. API-11.
   */
  fields: FieldError[];
  constructor(status: number, message: string, fields: FieldError[] = []) {
    super(message);
    this.status = status;
    this.fields = fields;
  }
}

//: FastAPI prefixes every `loc` with where it looked. That is useful to the
//: API author and noise to the person filling in the form.
const LOC_SOURCES = new Set(["body", "query", "path", "header", "cookie"]);

function humanise(segment: string): string {
  const words = segment.replace(/[_-]+/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/**
 * Turn one `{loc, msg}` entry into something a person can act on.
 *
 * `loc` is a path, not a name: `["body", "questions", 0, "max_marks"]` means
 * the fourth key of the first question. Numbers become 1-based because the
 * user counting questions on their screen starts at one.
 */
function toFieldError(item: { loc?: unknown[]; msg?: unknown }): FieldError | null {
  const message = typeof item.msg === "string" && item.msg ? humanise(item.msg) : "";
  if (!message) return null;

  const loc = Array.isArray(item.loc) ? [...item.loc] : [];
  if (loc.length > 0 && typeof loc[0] === "string" && LOC_SOURCES.has(loc[0])) {
    loc.shift();
  }
  const parts = loc.map((seg) => (typeof seg === "number" ? `#${seg + 1}` : humanise(String(seg))));
  return {
    path: loc.join("."),
    label: parts.join(" → "),
    message,
  };
}

/**
 * Read the `detail` of an error body in either shape the API produces.
 *
 * A handler-raised `HTTPException` gives a string. Schema validation gives a
 * list of `{loc, msg, type}`. This only ever read the string form, so every
 * field-level failure in the product fell through to `resp.statusText` and the
 * user was shown "Unprocessable Entity" — which names neither the field nor
 * the problem. API-11.
 */
export function parseErrorBody(body: unknown): { detail: string; fields: FieldError[] } {
  const detail = (body as { detail?: unknown } | null)?.detail;

  if (typeof detail === "string") return { detail, fields: [] };

  if (Array.isArray(detail)) {
    const fields = detail
      .filter(
        (item): item is { loc?: unknown[]; msg?: unknown } =>
          typeof item === "object" && item !== null,
      )
      .map(toFieldError)
      .filter((f): f is FieldError => f !== null);
    if (fields.length > 0) {
      return {
        detail: fields.map((f) => (f.label ? `${f.label}: ${f.message}` : f.message)).join("; "),
        fields,
      };
    }
  }

  return { detail: "", fields: [] };
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

export async function api<T>(path: string, options: RequestInit = {}, retry = true): Promise<T> {
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
    let fields: FieldError[] = [];
    try {
      const parsed = parseErrorBody(await resp.json());
      // Fall back to statusText only when the body told us nothing. An empty
      // string here would leave the user with a blank error box.
      if (parsed.detail) detail = parsed.detail;
      fields = parsed.fields;
    } catch {
      // non-JSON error body
    }
    throw new ApiError(resp.status, detail, fields);
  }
  if (resp.status === 204) return undefined as T;
  return (await resp.json()) as T;
}
