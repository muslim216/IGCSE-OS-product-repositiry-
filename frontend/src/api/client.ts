import type { components } from "./schema";

// Re-export API contract types from the generated OpenAPI schema (FE-4).
// The schema at src/api/schema.d.ts is produced by `npm run generate:api`
// from openapi.json, itself dumped from the backend's own OpenAPI document;
// hand-maintained mirrors are not added — the generated file is the source
// of truth and keeps frontend and backend in sync.
//
// The alias below is the point of the exercise: this pair used to be a
// hand-written `TokenPair` here, and the schema it mirrored has been called
// AccessToken on the server the whole time. Aliasing the *server's* name is
// what makes a rename over there a compile error over here rather than a
// silent divergence nobody notices (RISK-6).
export type TokenPair = components["schemas"]["AccessToken"];
export type User = components["schemas"]["UserOut"];
export type AuthResponse = components["schemas"]["AuthResponse"];

/**
 * Restore a response DTO's default-valued fields to required-nullable.
 *
 * A Pydantic field with a default (`x: T | None = None`) is absent from the
 * schema's `required` list, so the generated type marks it optional (`x?: …`,
 * i.e. `… | undefined`). But no endpoint here uses exclude_none/exclude_unset,
 * so every such field is always serialized — the value is `T | null`, never
 * missing. `Present` removes the optional modifier the generator added while
 * keeping the declared nullability, which is both what the backend actually
 * sends and the contract the app was built against.
 *
 * Only for RESPONSE types. Request bodies keep their optionality — there a
 * missing field is meaningfully different from a null one.
 */
export type Present<T> = { [K in keyof T]-?: T[K] };

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

/** The key used before the Avora rename (task 0.6).
 *
 * Read once, when the current key holds nothing, because renaming the key
 * alone signs out every browser that is currently signed in — and does it in
 * a way the refresh flow cannot repair: `api()` only attempts a refresh when a
 * stored access token exists, so a null read never reaches the httpOnly
 * refresh cookie sitting valid for another 30 days. The migration is one extra
 * read while signed out and none once a session exists. Delete this and its
 * branch below once the deploy is far enough behind that no browser can still
 * be holding the old key. */
const LEGACY_STORAGE_KEY = "igcse-os-tokens";

// Optional escape hatch for deployments without a same-origin API proxy
// (e.g. a Vercel preview without vercel.json applied yet).
export const API_BASE: string = import.meta.env.VITE_API_BASE_URL ?? "";

export function apiUrl(path: string): string {
  return `${API_BASE}${path}`;
}

/** A stored value, or null if it is not one we can use.
 *
 * Every request reads this, so anything unparseable would throw before the
 * fetch and take down the whole app — including the login that would replace
 * the bad entry. Discard it and let the user sign in again instead. */
function readStoredTokens(raw: string): StoredTokens | null {
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return null;
  }
  // JSON.parse succeeds on plenty of things that are not our shape — the
  // literal "null", a number, a quoted string — and none of them survives a
  // `typeof` check the way the previous `Partial<TokenPair>` cast implied.
  // `parsed.access_token` on `null` throws a TypeError uncaught by the block
  // above, which is exactly the crash this function exists to prevent.
  if (typeof parsed !== "object" || parsed === null) return null;
  const candidate = parsed as Partial<TokenPair>;
  if (typeof candidate.access_token !== "string" || !candidate.access_token) return null;
  return {
    access_token: candidate.access_token,
    token_type: typeof candidate.token_type === "string" ? candidate.token_type : "bearer",
  };
}

export function getStoredTokens(): StoredTokens | null {
  // The old key is cleared whenever this returns — a stale token left behind
  // is a credential nothing will ever use again, and worse than useless:
  // signing out removes only the current key, so a legacy value surviving here
  // would be migrated straight back on the next read and the app would look
  // signed in again until a request failed.
  //
  // But it is cleared only once the current key has been *parsed*, not merely
  // found. Dropping it on the presence of a current value discards a working
  // pre-rename session whenever the current entry is unusable — truncated by a
  // storage-quota write, half-written by another tab, edited by an extension —
  // and that session is exactly what this migration exists to save.
  const currentRaw = localStorage.getItem(STORAGE_KEY);
  const current = currentRaw === null ? null : readStoredTokens(currentRaw);
  if (current) {
    localStorage.removeItem(LEGACY_STORAGE_KEY);
    return current;
  }
  if (currentRaw !== null) localStorage.removeItem(STORAGE_KEY);

  const legacyRaw = localStorage.getItem(LEGACY_STORAGE_KEY);
  if (legacyRaw === null) return null;
  localStorage.removeItem(LEGACY_STORAGE_KEY);
  const legacy = readStoredTokens(legacyRaw);
  if (!legacy) return null;
  storeTokens(legacy);
  return legacy;
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
