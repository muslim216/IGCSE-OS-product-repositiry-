# ADR-0008 — Access token in the browser, refresh token in an httpOnly cookie

**Status:** Accepted · **Date:** 2026-08 (retroactive) · **Owner:** Architecture owner
**Supersedes:** — · **Superseded by:** —

## Context

MANARA is a single-page React application talking to a separate FastAPI backend. It needs
sessions that survive a page reload, work for students on shared or school devices, and can
be revoked immediately when a tutor resets a student's password.

The standard options are all flawed in different ways. Both tokens in `localStorage` hands a
30-day credential to any cross-site scripting flaw. Both in cookies invites cross-site
request forgery. A pure session cookie means the API cannot be called cross-origin at all.

## Decision

**Split the two tokens by lifetime and threat.**

- **Access token** — short-lived (30 minutes), sent as `Authorization: Bearer`, held in the
  browser at `localStorage["igcse-os-tokens"]`.
- **Refresh token** — 30 days, set as an **httpOnly, `SameSite=Lax` cookie scoped to
  `/api/v1/auth`**. Never persisted by JavaScript. `frontend/src/api/client.ts` deliberately
  does not write `refresh_token`, and says so in a block comment.

`POST /api/v1/auth/refresh` therefore sends an empty body and lets the cookie carry the
credential. `api<T>()` retries a 401 exactly once through that path.

Revocation is a **`token_version`** integer embedded in every token and re-checked on every
request by `get_current_user`. Bumping it invalidates every outstanding token for that user
instantly. Logout bumps it; so does a tutor resetting a student's password.

Two deployment consequences follow, and they are not optional:

- The API must be **same-origin**. Both deploys proxy `/api/*` to the backend (Vercel
  rewrite), so the browser sees one origin and a `SameSite=Lax` cookie is sent.
- `REFRESH_COOKIE_SECURE` defaults true; set false only for plain-HTTP local development,
  or browsers drop the cookie.

## Alternatives considered

**Both tokens in `localStorage`.** Simplest, and the common SPA pattern. Rejected: an XSS
flaw yields a 30-day credential that survives password changes until it expires. The whole
point of the split is that XSS costs at most 30 minutes.

**Both tokens in httpOnly cookies.** Better against XSS. Rejected: it makes every mutating
request a CSRF target, requiring a token-based defence — replacing one problem with another
and adding machinery.

**Session cookies with server-side session storage.** Would need shared session state, which
conflicts with the single-instance/scale-out story and adds a datastore (see
`governance/non-goals.md`).

**Short refresh tokens with silent rotation.** Better still, and more machinery than this
product currently justifies. A reasonable future step.

## Consequences

**Easier:** an XSS flaw yields a 30-minute credential, not a 30-day one. Revocation is
immediate and universal via `token_version` — a genuinely strong property that most JWT
deployments lack. Refresh needs no client-side token handling.

**Harder:** the same-origin requirement is a real constraint on deployment topology.
`VITE_API_BASE_URL` exists as a cross-origin escape hatch, but a build using it **cannot
refresh** — a `SameSite=Lax` cookie is not sent cross-site — so sessions silently end at
access-token expiry. That trap is documented in `README.md` and §08.

**The invariant this creates:** anything that invalidates a credential **must** bump
`token_version`. A password change that does not leaves the old refresh token minting access
tokens for its full 30 days, which is exactly the case a reset exists to stop. Any future
"change my password" or "disable account" endpoint inherits this obligation — it is a
Critical rule in §07.

## Revisit when

Refresh-token rotation with reuse detection becomes worth the machinery; or a mobile client
appears, where cookie semantics differ and this design needs re-examining rather than
copying.
