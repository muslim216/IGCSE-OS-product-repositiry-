# 07. Security Architecture

> **Volume 3 — Platform Engineering** · Engineering Constitution v1.2 · Status: Active
> **Owner:** Founder (see `governance/ownership.md`)
>
> Governs authentication, authorization, data protection, upload safety, secrets, and the AI
> trust boundary.

## Contents

- [Purpose](#purpose)
- [Scope](#scope)
- [Sources](#sources)
- [Principles](#principles)
- [Current Reality](#current-reality)
  - [Threat model](#threat-model)
  - [Data classification](#data-classification)
  - [Authentication](#authentication)
  - [Authorization](#authorization)
  - [Invites](#invites)
  - [Login throttling](#login-throttling)
  - [Upload safety](#upload-safety)
  - [OAuth and stored third-party credentials](#oauth-and-stored-third-party-credentials)
  - [Response headers and CSP](#response-headers-and-csp)
  - [The AI trust boundary](#the-ai-trust-boundary)
  - [Secrets](#secrets)
- [Standards](#standards)
- [Known Gaps](#known-gaps)
- [Review Triggers](#review-triggers)

---

## Purpose

Avora holds named children's academic records, their parents' contact details, and
photographs of their handwriting, and it lets an AI put marks on those records without a
human in the loop. This document defines what protects that, states the invariants that are
load-bearing rather than stylistic, and records honestly where the controls are good and
where the governance around them does not exist.

Several rules here are **Critical**: breaking one is a vulnerability, not a style regression.

## Scope

**In scope:** the threat model; data classification; the token model and revocation;
authorization and tenant isolation; invite bounds; login throttling; upload validation; OAuth
and encrypted third-party credentials; response headers and CSP; the prompt-injection
boundary; secrets handling and rotation; dependency policy.

**Out of scope:** the endpoint-level rules that implement authorization (§05); the deployment
that carries the CSP (§08); AI routing mechanics (§09); incident response and rotation
procedures (§14).

### Non-goals

- **No third-party authentication.** No SSO, no social login. Students often have no email
  address; a tutor creates the account. Adding an identity provider would not remove the
  local path.
- **No multi-factor authentication.** For a tutor's own account this is a defensible future
  addition; for a twelve-year-old submitting homework it would be an adoption barrier with a
  worse failure mode than the threat it addresses.
- **No field-level encryption in the database.** One field is encrypted — the Google refresh
  token — because it is a live credential for a third-party system. Academic records are
  protected by access control and by the database's own encryption at rest.
- **No security through ID unguessability.** Primary keys are sequential integers
  (`ADR-0007` family, `governance/non-goals.md`). Every authorization decision is explicit.
- **No self-service password reset by email.** Students may have no email; a tutor resets it,
  which is also why that path must revoke sessions.

## Sources

Written from: `backend/app/security.py`; `backend/app/api/deps.py`; `backend/app/api/auth.py`;
`backend/app/services/rate_limit.py`; `backend/app/services/storage.py`;
`backend/app/services/invites.py`; `backend/app/services/google_classroom.py`;
`backend/app/services/prompts.py`; `backend/app/main.py` (`SECURITY_HEADERS`);
`backend/app/config.py`; `frontend/vercel.json`; `frontend/src/api/client.ts`;
`backend/tests/test_security_hardening.py`; `render.yaml`.

---

## Principles

**P1 — The server decides.** The client is fully under the user's control. Route guards,
hidden buttons, and disabled inputs are user experience. Every authorization decision happens
in the API or below.

**P2 — A credential that cannot be revoked is not a credential.** Every token embeds a
version that is re-checked on every request, so any event that should end a session can end
it immediately.

**P3 — Untrusted input includes the student's page.** A submission is a photograph of
something a person wrote, fed to a model whose output can become a mark with no human review.
It is data, never instruction.

**P4 — Degrade to a clear state, never to an open one.** A missing key produces a "not
configured" error. An unrecognized upload type is refused. An unknown MIME fails the magic-byte
check because the lookup returns nothing to match.

**P5 — Isolation is per-query, not per-request.** Tenancy is enforced by every query filtering
on organization. There is no ambient scope, which means there is no single place that can be
got right once.

---

## Current Reality

### Threat model

The actors that matter, in rough order of likelihood:

| Actor | Capability | What they want | Primary controls |
|---|---|---|---|
| **A student of the platform** | A valid account, full control of their browser, and control of the content of their own submitted pages | Better marks; other students' work; the mark scheme | Role checks, ownership checks, tutor-only mark-scheme download, the marking prompt's injection boundary, one-remark-request-per-question |
| **A tutor of another organization** | A valid account in a different tenant | Another tutor's materials, students, or past papers | `organization_id` filtering on every query; (organization, subject) scoping for shared subjects |
| **An unauthenticated attacker** | Network access to a public API | Account takeover; enumeration | bcrypt, per-identifier login throttling, uniform 404s, short access tokens |
| **A parent** | An account linked to one child | Another child's record | Single-use parent-link invites; `ParentLink` checked per query |
| **Someone with an XSS foothold** | Script execution in a signed-in page | A durable credential | Strict CSP (`script-src 'self'`), refresh token in an httpOnly cookie, 30-minute access token |
| **A malicious upload** | Any file the size limit allows | Stored XSS, or content re-interpreted as executable | Magic-byte validation, MIME allowlist, server-generated filenames, `nosniff`, attachment disposition |
| **An operator error** | Deploy and configuration access | — | This is the most likely actual cause of an incident; see §08 and §14 |

**Explicitly out of the model:** a compromised hosting provider, a malicious AI provider, and
a determined insider with database access. Nothing here defends against those.

### Data classification

Four classes. This is net-new — no classification existed before this document.

| Class | Examples | Handling |
|---|---|---|
| **C1 — Secret** | `JWT_SECRET`, `GOOGLE_TOKEN_ENCRYPTION_KEY`, API keys, database credentials, stored Google refresh tokens | Never in the repository, never in logs, never in an API response. Encrypted at rest where stored in the database. Rotation procedure in §14. |
| **C2 — Sensitive personal (minors)** | Student names, academic records, readiness scores, mistakes, tutor notes, images of student handwriting, parent contact details | Access requires an explicit authorization decision. Never in logs, never in an error message, never sent to a third party except the AI providers under `AI-*` rules. |
| **C3 — Internal** | Assignments, classifieds, past papers, mark schemes, Knowledge Base entries, organization settings | Organization-scoped. Mark schemes are tutor-only. |
| **C4 — Public** | Syllabus topic trees, subject metadata, the landing page | Shared across organizations by design. |

**The five built-in syllabuses are C4 and deliberately global**, which is precisely why
scoping by subject alone leaks C3 across tenants — see `SEC-8`.

### Authentication

Passwords are bcrypt (`hash_password` / `verify_password` in `security.py`).
`verify_password` catches `ValueError` and returns `False`, so a malformed stored hash fails
closed rather than raising.

Tokens are HS256 JWTs with the payload `{sub, tv, type, iat, exp}`:

| Token | Lifetime | Transport | Storage |
|---|---|---|---|
| Access | 30 minutes (`access_token_expire_minutes`) | `Authorization: Bearer` | `localStorage["avora-tokens"]` |
| Refresh | 30 days (`refresh_token_expire_days`) | httpOnly `SameSite=Lax` cookie scoped to `/api/v1/auth` | The cookie only — never script-readable |
| OAuth state | 10 minutes (`STATE_TOKEN_TTL`) | Query parameter | Not stored server-side |

`decode_token(token, expected_type)` verifies the signature, **checks `type` matches**, and
returns `(user_id, token_version)`. Type checking is what stops a refresh token being
presented as an access token.

**`token_version` is the revocation mechanism.** Every token embeds `tv`; `get_current_user`
re-reads the user on every request and rejects when `tv` ≠ `user.token_version` with "Token
has been revoked". Bumping the column invalidates every outstanding token for that user
instantly — both kinds, everywhere.

Two events bump it today: **logout** (`POST /api/v1/auth/logout`, which requires a valid access
token and also clears the cookie) and **a tutor resetting a student's password**. The second
matters: a reset is how a tutor evicts whoever else has been using a shared account, so it has
to end the sessions that account already has, not merely change what a new sign-in needs.

See `ADR-0008` for why the two tokens are stored differently.

### Authorization

Two independent checks, both required: **role** (what kind of user) and **ownership or
organization** (which rows).

**The role check is a dependency.** A handler declares what it needs in its signature:

```python
async def get_preferences(db: DbSession, user: TutorUser) -> PreferencesOut:
```

`TutorUser` (tutor or admin → 403 `Tutor account required`) gates 38 routes and `StudentUser`
(→ 403 `Student account required`) gates 13. `require_role(*roles, detail=...)` builds the
same gate with a different message and is used once, by `reports.generate`. The seven
ownership helpers that sit below the routing layer take a plain `User` and call
`assert_tutor()` / `assert_student()` rather than repeating the condition — that matters
because nine `groups.py` handlers have no gate of their own and rely entirely on
`_owned_group`'s.

**Why this is a security property and not a style one.** A dependency in the signature fails
closed: a request cannot be resolved without it. An imperative call in the body fails **open**:
forget the line and the endpoint authenticates fine and authorizes nothing — no test, no
linter and no type error would say so.

Until recently that was the real state of this codebase: ten byte-identical `_require_tutor`
copies plus one `_require_student`, called at the top of 35 handler bodies, while
`require_role` sat unused in `deps.py`. Converging them was only half the fix.
`tests/test_authorization.py` is the other half — it holds an explicit inventory of the eight
routes reachable without a token, asserts no route becomes public by accident, asserts the
gates are one shared dependency by *identity* rather than by shape, and fails if any router
grows its own copy of the helper again. See `RISK-7`.

**Organization scoping did not converge.** It is still applied per query with
`user.organization_id`, which satisfies `SEC-7` but by convention — a new query that omits the
filter is exactly the failure the role gate no longer has. `get_current_org_id` and
`CurrentOrg` remain unused; do not cite either as the mechanism.

Two authorization traps are already known and both have bitten:

- **`Submission` is polymorphic.** A past-paper submission has `assignment_id = None`, so
  reading it unconditionally raises *inside* an authorization check. `_tutor_owns()` in
  `api/submissions.py` is the only place that branch may live (`API-20`).
- **Subjects are global.** Scoping student-visible material by subject alone shows every
  tutor's uploads to every student. `_enrolled_scope` in `api/past_papers.py` scopes by
  (organization, subject) derived from the student's actual group memberships.

### Invites

`services/invites.py` bounds every invite: **all expire after 14 days**, and **parent-link
codes are single-use**, enforced by `invites.used_at` (migration 0021) rather than by
convention — one of them exposes a named child's entire record.

Invites are minted with `build_invite()` and validated with `check_usable()`. Constructing an
`Invite` directly bypasses the policy.

### Login throttling

`services/rate_limit.py` enforces **10 failed logins per identifier per 15 minutes**, reset on
success so a user who finally remembers their password is not still locked out.

**Per identifier, not per IP** — deliberate, and the docstring explains it: the API sits behind
Render's proxy, where one shared source address would mean a global lockout.

**Two stores, one policy** (task 1.4, AV-83). `RateLimiter` counts in Redis when `REDIS_URL` is
set, so N instances enforce one limit rather than N copies of it, and in a process-local
`FixedWindowLimiter` when it is not. **Redis holds rate-limit counters and nothing else**
(`E18`) — Postgres remains the source of truth for application state, and a second use of Redis
is its own decision.

`REDIS_URL` is **unset in `render.yaml`**, deliberately: with one instance running, in-process
counters *are* the correct limit, and a Redis nobody needs is a dependency that can only take
logins down. Setting it belongs to the scale-out cutover gated on 11.2 (`AV-85`).

**Redis is never an authentication dependency in either direction** (threat review F4, AV-97). A
configured Redis that stops answering falls back to the in-process counter and raises an alarm:
blocking every login would be an outage an attacker triggers by degrading Redis, and leaving
failures uncounted would be a free credential-stuffing window. The fallback is loud on purpose —
the first failure logs at ERROR and `/api/v1/health/ready` reports `rate_limit.degraded` and
answers `503` — because a silent fallback is the same as no fallback. A circuit breaker opens
after three consecutive failures so a sustained outage costs one timed-out call per 30s rather
than two per login.

Keys are `avora:rl:{purpose}:{scope}:{sha256(identifier)[:32]}`, where `scope` is `global` or
`tenant:{id}` — prefixed so a caller passing the literal string `"global"` as a tenant cannot
land on the unscoped counter. Namespaced by purpose and tenant so
one caller cannot consume or collide with another's allowance; the identifier is **hashed**
because a Redis keyspace is readable by anything holding the connection string, and a store
explicitly not the source of truth must not double as a roster of who has an account. Login's
tenant is `global`: the lookup in `api/auth.py` matches an email or username across every
organization, so there is no tenant to scope to until after the credential is accepted.

The in-process store self-evicts stale windows above 10,000 keys so a long-running process
cannot accumulate an entry per attempted username; Redis keys carry a TTL instead. The window is
fixed rather than sliding — a burst straddling a boundary can briefly exceed the limit, accepted
deliberately as the price of a counter that is one `INCR`.

Nothing else in the API is rate limited. (The chat daily message cap was the other one, until
task 0.3 deleted the surface it capped, AV-57.)

### Upload safety

`services/storage.py`, and it is the most carefully built module in the codebase.

- **20 MB per file** (`MAX_FILE_BYTES`).
- **Allowlist**: PDF, JPEG, PNG, WebP. HEIC/HEIF are accepted and **transcoded to JPEG on the
  way in**, because iPhones photograph in HEIC by default and the marking pipeline passes the
  stored MIME straight to an image API that does not accept it.
- **Magic-byte validation** (`content_matches_mime`). The declared `Content-Type` is
  client-supplied and decides nothing on its own. `_MAGIC` holds the required leading bytes;
  WebP is checked as a RIFF container. **An unknown MIME matches nothing and fails**, so the
  check fails closed.
- **Decoding doubles as validation** for HEIC: bytes that merely claim to be HEIC fail in the
  transcode rather than being stored.
- **Size is checked before normalization.** `save_bytes` caps the *source* bytes before
  `_normalize`, with a comment explaining why: checking only afterwards would both feed an
  arbitrarily large image to the decoder and then measure the smaller transcoded JPEG.
- **Filenames are server-generated** — `secrets.token_hex(16)` plus an extension from the
  allowlist. The client's filename is stored as metadata and never used as a path.
- **`delete_file` tolerates a missing file**, used to undo a write when a later step in the
  same request fails — a file with no row pointing at it is invisible and can never be cleaned
  up.

Paths in the database are **relative** to `UPLOAD_DIR`, so the directory can move to object
storage without touching rows.

### OAuth and stored third-party credentials

Google Classroom uses per-tutor OAuth. Two controls matter:

**The `state` parameter is verified server-side.** `create_state_token(user_id, purpose)`
issues a signed, 10-minute token bound to the user who started the flow, with a nonce;
`verify_state_token` re-checks signature, type, purpose, and subject. The docstring is explicit
about why the browser's `sessionStorage` comparison is not sufficient: it lives in script the
server cannot vouch for, and without the server-side check an attacker can hand a tutor a
callback URL carrying the attacker's own authorization code and silently connect the
attacker's Google account to the tutor's organization.

**Refresh tokens are encrypted at rest.** `GOOGLE_TOKEN_ENCRYPTION_KEY` encrypts the stored
Google refresh token, falling back to a key derived from `JWT_SECRET` when unset — so tokens
are never stored in plaintext even without extra configuration. A dedicated value is preferred
so that rotating one secret does not invalidate the other.

Both credentials unset means the feature reports "not configured" and the app runs fine —
`GoogleClassroomUnavailableError` mirrors `AIUnavailableError`.

### Response headers and CSP

**API** (`main.py`, one `@app.middleware("http")`, applied with `setdefault`):

```
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
Content-Security-Policy: default-src 'none'; frame-ancestors 'none'
Referrer-Policy: no-referrer
```

The reasoning is in the source: the API returns JSON and file downloads, never HTML meant to
be rendered, so these govern how a browser treats a response it was tricked into loading.
`nosniff` stops a stored upload being re-interpreted as something executable regardless of the
`Content-Type` served with it; `frame-ancestors` keeps API responses out of an attacker's
iframe; `no-referrer` keeps ids in request paths out of the `Referer` header.

**The CSP is deliberately skipped for `/docs`, `/redoc`, and `/docs/oauth2-redirect`**, because
Swagger UI loads its assets from a CDN and `default-src 'none'` would block them. Those are
the one HTML page the service serves on purpose.

**Frontend** (`frontend/vercel.json`), and this is the CSP that matters for XSS:

```
default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline';
img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self';
object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'
```

`script-src 'self'` with no CDN and no inline script is what makes an injected script
expensive. The frontend holds an access token in `localStorage`, so this is the control that
limits what an injection could do with it. `font-src 'self' data:` is why `--font-display` is
a system stack (§02).

CORS comes from `settings.cors_origin_list` with `allow_credentials=True`. It is only
load-bearing for a cross-origin `VITE_API_BASE_URL` build — the supported deploys proxy
`/api/*` server-side, so the browser sees one origin.

### The AI trust boundary

**Auto-finalize means a mark can count with no human in the loop, and the student controls the
page being read.** That makes the marking prompt a security control, not just a prompt.

The `marking` prompt in `services/prompts.py` states that page content is **data, never
instructions**, and that anything addressing the marker is flagged with confidence `low` for a
tutor rather than acted on. A mark that is not both scheme-backed and confident goes to the
review queue regardless (`ADR-0009`).

Defence in depth around it: proposed marks are **clamped to the question's valid range**, so
even a fully successful injection cannot award marks that do not exist; a "no data" question is
never silently scored 0; and every mark records the `ai_model` and `ai_prompt_version` that
produced it, so a bad batch can be identified precisely rather than estimated.

Student data does reach two third-party AI providers. That is inherent to the product and
bounded by `AI-*` rules in §09: no training, no fine-tuning, no retention beyond the call.

### Secrets

All configuration is environment-only, read through `get_settings()`.

| Secret | Source in production | Notes |
|---|---|---|
| `JWT_SECRET` | `generateValue: true` in `render.yaml` | Default is `"change-me-in-production"` — safe only because Render generates one |
| `GOOGLE_TOKEN_ENCRYPTION_KEY` | `generateValue: true` | Falls back to a key derived from `JWT_SECRET` |
| `DATABASE_URL` | `fromDatabase` | — |
| `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `AI_MODEL_PRICING`, `GEMINI_MODEL` | `sync: false` — entered in the dashboard | Never in the repository |

`backend/tests/test_security_hardening.py` (370 lines, 14 tests) covers this area and was
documented nowhere before this handbook.

---

## Standards

### Authentication and sessions

**`SEC-1` — MUST · Critical · Active**
Any event that should invalidate a credential bumps `users.token_version`. Logout and
tutor-initiated password reset do; any future password change, account disable, or
compromise-response endpoint must.
*Rationale:* without the bump, an existing refresh token keeps minting access tokens for its
full 30 days — precisely the case a reset exists to stop.

**`SEC-2` — MUST NOT · Critical · Active**
Never persist a refresh token anywhere script can read it — `localStorage`, `sessionStorage`,
IndexedDB, or a non-httpOnly cookie.
*Rationale:* the split in `ADR-0008` exists so an XSS foothold costs 30 minutes rather than 30
days. Same rule as `FE-2`, stated from both sides deliberately.

**`SEC-3` — MUST · Critical · Active**
Every token verification checks the token `type` matches what the caller expects, via
`decode_token(token, expected_type=...)`.
*Rationale:* without it a 30-day refresh token is accepted wherever a 30-minute access token
is.

**`SEC-4` — MUST · Critical · Active**
Passwords are hashed with bcrypt through `security.hash_password`. Never store, log, or return
a password or a hash.
*Rationale:* the only acceptable handling; a hash in a log is a hash in an attacker's hands.

**`SEC-5` — MUST NOT · Important · Active**
Never lengthen the access token's lifetime to avoid a refresh problem.
*Rationale:* the short lifetime is the mitigation for storing it in `localStorage`; extending
it silently trades away the reason the split exists.

### Authorization and isolation

**`SEC-6` — MUST · Critical · Active**
Every non-public endpoint enforces a role check **and** an ownership or organization check.
Authentication alone is never sufficient.
*Rationale:* role says what kind of user; ownership says which rows. Integer keys are
enumerable, so ownership is the only thing between a student and another student's record.

**`SEC-7` — MUST · Critical · Active**
Every query returning tenant data filters on `organization_id`, derived from the authenticated
user — never from a path or body parameter.
*Rationale:* a client-supplied organization id is an authorization bypass with extra steps.

**`SEC-8` — MUST · Critical · Active**
Student-visible material is scoped by (organization, subject) derived from the student's group
memberships, never by subject alone.
*Rationale:* subjects are C4 and shared globally, so subject-only scoping exposes every
organization's C3 material. `_enrolled_scope` in `api/past_papers.py` is the reference.

**`SEC-9` — MUST · Critical · Active**
Return `404`, not `403`, for a resource the caller may not know exists — including anything
belonging to another organization.
*Rationale:* a distinguishable `403` confirms existence, and sequential integer keys make that
an enumeration oracle. Implements `API-7`.

**`SEC-10` — MUST NOT · Critical · Active**
Never treat a frontend role gate, hidden control, or disabled input as an authorization
control.
*Rationale:* P1. The client is the attacker's own software.

**`SEC-11` — MUST · Critical · Active**
A role gate is declared in the handler signature (`TutorUser`, `StudentUser`, or
`require_role(...)` where the message must differ), never as a module-local helper called from
the handler body. An ownership helper below the routing layer calls `assert_tutor()` /
`assert_student()`.
*Rationale:* a dependency in the signature fails closed; an imperative call in the body fails
open, and nothing detects the omission. Promoted from Draft when all 23 routers were converged
and `tests/test_authorization.py` made the property enforceable. `RISK-7`. Mirrors `BE-17`.

### Credentials and invites

**`SEC-12` — MUST · Critical · Active**
Every invite expires. Any invite granting access to an individual's record is single-use,
enforced by a database constraint or column, not by application convention.
*Rationale:* a parent-link code exposes a named child's entire record; reusability turns one
leaked link into unlimited access.

**`SEC-13` — MUST · Important · Active**
Mint invites with `build_invite()` and validate with `check_usable()`. Never construct an
`Invite` directly.
*Rationale:* the expiry and single-use policy lives in those functions; a direct construction
silently opts out.

**`SEC-14` — MUST · Important · Active**
Authentication failures are throttled per identifier, not per source address.
*Rationale:* the API sits behind a proxy where one shared address would mean a global lockout —
a denial-of-service dressed as a control.

**`SEC-29` — MUST · Important · Active**
A rate limiter whose shared store fails **falls back to counting in-process and raises an
alarm**. It never blocks the request wholesale, and never lets the attempt go uncounted.
*Rationale:* threat review F4 (`AV-97`). Blocking is an authentication outage an attacker
triggers by degrading the store; not counting is a free credential-stuffing window. Degrading
from one global limit to one per instance is the middle, and it is the behaviour that shipped
before the store existed. The alarm is not optional — a silent fallback is the same as no
fallback, so the path carries its own test and `/health/ready` reports it.

**`SEC-30` — MUST · Important · Active**
Rate-limit keys are namespaced by purpose and tenant, and the identifier is hashed rather than
embedded.
*Rationale:* namespacing stops one caller consuming or colliding with another's allowance. The
hash keeps a store that is explicitly *not* the source of truth from becoming a readable roster
of who has an account — a Redis keyspace is enumerable by anything holding the connection
string.

### Uploads and files

**`SEC-15` — MUST · Critical · Active**
Uploads are validated by magic bytes through `services/storage.py`. The client's
`Content-Type` never decides acceptance on its own, and an unrecognized type fails.
*Rationale:* `Content-Type` is attacker-controlled; a `.exe` announced as `image/png` would
otherwise be stored and served under that type.

**`SEC-16` — MUST · Critical · Active**
Stored filenames are server-generated. A client-supplied filename is metadata only and never
forms part of a path.
*Rationale:* path traversal, and collisions that let one upload overwrite another.

**`SEC-17` — MUST · Important · Active**
Enforce the size limit on the **source** bytes, before any decode or transcode.
*Rationale:* checking afterwards feeds an arbitrarily large image to the decoder and then
measures the smaller output — a decompression bomb. `save_bytes` already does this.

**`SEC-18` — MUST · Important · Active**
A file download is authorized by the same ownership rules as its parent record. A past paper's
mark scheme is tutor-only.
*Rationale:* the file is the material; an unauthorized download is the leak the record's
permissions exist to prevent.

**`SEC-19` — MUST · Important · Active**
A write that is not committed is undone. Use `delete_file()` when a later step in the same
request fails.
*Rationale:* a file with no row pointing at it is invisible, unreclaimable, and counts against
a 10 GB disk (`RISK-8`).

### AI trust boundary

**`SEC-20` — MUST · Critical · Active**
Any prompt processing user-supplied content states that the content is data and never
instructions, and directs the model to flag rather than obey anything addressing it.
*Rationale:* auto-finalize means the output can become a mark with no human in the loop, and
the student controls the page.

**`SEC-21` — MUST · Critical · Active**
If a prompt carrying a safety instruction is rewritten, the instruction is preserved and the
prompt's `version` is bumped.
*Rationale:* the version is stamped on every produced record, so it is how a bad batch is
identified; silently changing a safety rule makes that trace meaningless.

**`SEC-22` — MUST · Critical · Active**
AI-proposed values are clamped to their valid range before storage, and a "no data" answer is
never coerced to a number.
*Rationale:* defence in depth — even a fully successful injection cannot award marks that do
not exist.

**`SEC-23` — MUST NOT · Critical · Active**
Never send C1 secrets to an AI provider, and never send C2 data to any third party other than
the configured AI providers.
*Rationale:* the AI providers are a deliberate, bounded exception; anything else is an
undisclosed disclosure of minors' data.

### Secrets and dependencies

**`SEC-24` — MUST NOT · Critical · Active**
Never commit a secret. All configuration is environment-only, read via `get_settings()`.
*Rationale:* repository history is permanent; a committed key is rotated, not deleted.

**`SEC-25` — MUST NOT · Critical · Active**
Never log or return a secret, a token, a password, or C2 personal data. Error messages carry
what happened, not the values involved.
*Rationale:* logs are read by more people and systems than the database is, and `API-9`
already forbids leaking internals to clients.

**`SEC-26` — MUST · Important · Active**
A stored third-party credential is encrypted at rest with a dedicated key.
*Rationale:* a Google refresh token is a live credential for a system Avora does not control;
the `JWT_SECRET`-derived fallback exists so it is never plaintext, not as the intended
configuration.

**`SEC-27` — SHOULD · Important · Active**
Dependencies are pinned by a lockfile and scanned for known vulnerabilities before release.
*Rationale:* `pip install .` against `>=` ranges means two builds of one commit can differ, and
nothing currently scans anything (`RISK-11`).

**`SEC-28` — SHOULD · Important · Active**
Application containers run as a non-root user.
*Rationale:* least privilege; the image currently runs as root.

---

## Known Gaps

| Gap | Why it matters | Severity |
|---|---|---|
| **Organization scoping is still a convention, not a mechanism.** `get_current_org_id` and `CurrentOrg` remain dead code. | The role half of `RISK-7` closed; this half did not. A query that omits the organization filter fails open with nothing to detect it — `SEC-7` rests on every author remembering. | `before scale` |
| **No security-specific job in CI.** `.github/workflows/ci.yml` runs the whole suite, so `test_security_hardening.py` and `test_authorization.py` do gate every PR — but there is no dependency audit, no secret scan in the workflow, and no SAST. | The rules with tests behind them are now enforced; the rest are still enforced by review alone. `RISK-2` residual. | `before scale` |
| **No dependency pinning or vulnerability scanning.** No lockfile; `pip install .` resolves `>=` ranges at build time. | Non-reproducible builds and no signal on a published CVE. `RISK-11`, `SEC-27`. | `before scale` |
| **The container runs as root** with no `.dockerignore`. | Breaks `SEC-28`; the build context also carries whatever is in the directory. | `before scale` |
| **No data retention or deletion policy**, and no subject-access or erasure path. | C2 data on minors is kept indefinitely with no defined basis or route to remove it. `RISK-9`. | `before scale` |
| **No security logging.** Failed authorization, token revocation, and password resets are not recorded anywhere. | A compromise could not be reconstructed. Compounded by there being no request ids at all (§11). | `before scale` |
| ~~**Login throttling is per-process.**~~ **Closed** by task 1.4 (`AV-83`): `RateLimiter` shares counters through Redis. Capability only — `REDIS_URL` is unset in `render.yaml`, so the live deployment is still per-process, which is correct at its one instance. | `RISK-1`'s third link. Setting `REDIS_URL` is part of the scale-out cutover gated on 11.2. | `closed (capability)` |
| **One account can be addressed by two identifiers.** The counter is keyed on what the caller typed, and `api/auth.py` matches an account by email *or* username — so knowing both yields two counters and twice the allowance against one account. Pre-dates the Redis work (the in-process limiter keyed the same way). | Weakens `SEC-14` by a factor of two for any account whose username is guessable. Resolving to a user id before counting would mean looking the account up *before* throttling, reintroducing the timing oracle `_dummy_hash()` exists to close — so the fix is a canonicalization step, not a reordering. | `before scale` |
| **Only login is rate limited.** AI-triggering endpoints are unbounded per user. (Chat was the other one, until task 0.3 deleted the surface, AV-57.) | A single account can drive arbitrary AI spend (`RISK-12`). | `before scale` |
| **No MFA for tutor accounts.** | A tutor account holds every student's C2 data; password-only is the whole control. Deliberate for students, arguable for tutors. | `nice to have` |
| **`JWT_SECRET` defaults to `"change-me-in-production"`.** Safe only because `render.yaml` generates one. | Any deployment not using the blueprint inherits a known signing key. | `before scale` |

---

## Review Triggers

Update this document when:

- The token model, lifetime, storage, or revocation mechanism changes.
- A new event should invalidate credentials — it must be added to `SEC-1`.
- `api/deps.py`'s authorization surface changes, or `CurrentOrg` is adopted.
- A route's role gate changes, or `PUBLIC_ROUTES` in `tests/test_authorization.py` grows.
- `services/storage.py`'s allowlist, limits, or validation changes.
- A CSP or security header changes in `main.py` or `frontend/vercel.json`.
- A new third-party integration stores a credential.
- A prompt carrying a safety instruction is rewritten.
- A new data class appears that does not fit C1–C4.
- Any authentication or authorization vulnerability is found — record what allowed it.
