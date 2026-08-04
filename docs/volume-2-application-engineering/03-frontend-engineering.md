# 03. Frontend Engineering

> **Volume 2 — Application Engineering** · Engineering Constitution v1.0 · Status: Active
> **Owner:** Founder (see `governance/ownership.md`)
>
> Governs how the React application is structured, routed, and connected to the API.

## Contents

- [Purpose](#purpose)
- [Scope](#scope)
- [Sources](#sources)
- [Principles](#principles)
- [Current Reality](#current-reality)
- [Standards](#standards)
- [Known Gaps](#known-gaps)
- [Review Triggers](#review-triggers)

---

## Purpose

Answers *how do I add or change something in `frontend/src/` without breaking the parts that
are load-bearing*. Three things in this codebase look ordinary and are not: the single HTTP
entry point with its transparent refresh, the deliberate exclusion of the refresh token from
storage, and the hand-mirrored API types that nothing checks.

## Scope

**In scope:** application structure and file organization; routing and role gating; the API
client contract; TanStack Query conventions; state management; forms, errors, and uploads;
build and type configuration; the checklist for adding a page.

**Out of scope:** visual design, tokens, and accessibility rules (§02); the API being called
(§05); token semantics and threat model (§07); bundle and render performance budgets (§10);
testing (§12); TypeScript style (§13).

### Non-goals

- **No global state library.** No Redux, Zustand, or Jotai. Server state is TanStack Query;
  auth is one context; everything else is `useState`.
- **No component library.** See §02.
- **No server-side rendering.** A static SPA on Vercel with an `/api/*` rewrite. SSR would
  break the same-origin cookie arrangement `ADR-0008` depends on and buy nothing for an
  authenticated tool behind a login.
- **No client-side routing library beyond React Router.**
- **No raw `fetch` outside `api/`.**

## Sources

Written from: `frontend/src/main.tsx`, `App.tsx`, `api/client.ts`, `auth/AuthContext.tsx`,
`auth/ProtectedRoute.tsx`, `components/AppShell.tsx`; the 13 modules in `frontend/src/api/`;
`frontend/vite.config.ts`; `frontend/tsconfig.json`; `frontend/package.json`;
`frontend/vercel.json`.

---

## Principles

**P1 — One way in and out.** Every HTTP call goes through `api<T>()`. It is where
authentication, refresh, and error normalization live, and a call that bypasses it silently
opts out of all three.

**P2 — The browser holds the smallest credential that works.** The access token is in
`localStorage` because it must be readable to be sent. The refresh token is not, because it
does not have to be.

**P3 — Server state is not application state.** Data from the API is cached, invalidated, and
refetched by TanStack Query. Copying it into `useState` creates a second source of truth that
will be stale.

**P4 — The interface is organized by who uses it.** Top-level folders are roles, because the
product's surfaces differ by role and route guards follow the same lines.

---

## Current Reality

### Structure

```
frontend/src/
  main.tsx        StrictMode > QueryClientProvider > AuthProvider > BrowserRouter > App
  App.tsx         all routes and the two nav arrays
  index.css       the design system (§02)
  api/            13 modules — client.ts plus one per domain
  auth/           AuthContext, ProtectedRoute, and the 4 unauthenticated pages
  components/     shared: ui.tsx, AppShell, Markdown, ReadinessTable, ReadinessView, …
  lib/            pure helpers: readiness.ts, schedule.ts
  marketing/      LandingPage
  tutor/          17 pages, plus tabs/ and today/ subfolders
  student/        10 pages
  parent/         ParentDashboard
  test/           7 spec files and setup.ts
```

Roughly 9,800 lines including CSS. The largest pages are
`tutor/AssignmentDetailPage.tsx` (368), `tutor/SubmissionReviewPage.tsx` (345), and
`tutor/SyllabusUploadPage.tsx` (326).

### Routing and role gating

All routes live in `App.tsx`. The shape is a `ProtectedRoute` wrapping an `AppShell`:

```tsx
<Route element={<ProtectedRoute roles={["tutor", "admin"]} />}>
  <Route element={<AppShell title="Tutor" nav={TUTOR_NAV} />}>
    <Route path="/tutor" element={<TodayDashboard />} />
    …
```

- **Public:** `/`, `/login`, `/signup`, `/join/:code`, `/parent-join/:code`. `/` renders
  `LandingPage` when signed out and redirects to `homePathFor(user)` when signed in.
- **Tutor** (`roles={["tutor","admin"]}`): `/tutor` and children, including the nested
  `GroupLayout` at `/tutor/groups/:groupId` with tabs `homework | students | syllabus |
  schedule | resources | analytics | new-homework | mock`. `/settings/classroom/callback`
  sits inside the tutor guard but outside the shell.
- **Student** (`roles={["student"]}`): `/student` and nine siblings.
- **Parent** (`roles={["parent"]}`): `/parent`, with no nav array.
- **Catch-all:** `*` redirects to `/`.

Navigation is data-driven: `STUDENT_NAV` (8 entries, `/student/tutor` carrying
`slot: "bottom"`) and `TUTOR_NAV` (9 entries), each `{ to, label, icon }` with `lucide-react`
icons.

**Route guards are a convenience, not a control.** `ProtectedRoute` hides interface; the API
enforces authorization. Never treat a role gate as a security boundary — see `SEC` rules in
§07.

### The API client

`frontend/src/api/client.ts` is the only place `fetch` is configured. `api<T>(path, options,
retry = true)`:

1. Reads the access token from `localStorage["igcse-os-tokens"]` and sets
   `Authorization: Bearer`.
2. Sets `Content-Type: application/json` unless the body is `FormData` — so multipart uploads
   get the browser's own boundary header.
3. Always sends `credentials: "include"`, which is what carries the httpOnly refresh cookie.
4. On `401` **with a token present**, calls `refreshTokens()` once and retries exactly once
   (`retry = false` on the recursive call, so there is no loop).
5. On a non-ok response throws `ApiError(status, detail)`.
6. Returns `undefined as T` for `204`.

**The refresh token is never persisted.** `storeTokens()` narrows whatever it is given to
`{ access_token, token_type }`, so a caller passing a whole login response cannot accidentally
write `refresh_token`. `refreshTokens()` posts an **empty body** and lets the cookie carry the
credential. The reasoning is written out at `client.ts:20–31` and `93–100`.

**This requires the API to be same-origin.** Both deploys proxy `/api/*` to the backend, so
the browser sees one origin. `API_BASE` is `import.meta.env.VITE_API_BASE_URL ?? ""` — an
escape hatch for a preview without the rewrite — and **a build using it cannot refresh**,
because a `SameSite=Lax` cookie is not sent cross-site. Sessions there end at access-token
expiry.

`getStoredTokens()` defensively discards unparseable or malformed storage rather than
throwing, with a comment explaining why: every request reads it, so a throw here would take
down the app including the login that would fix it.

**Two deliberate bypasses** of `api<T>()` exist and are the only sanctioned ones:

- `homework.ts:fetchFileUrl()` — fetches a file as a blob for `URL.createObjectURL`, because
  an authenticated file cannot be an `<img src>`.
- `chat.ts:streamMessage()` — Server-Sent Events, with its own 401-refresh-and-retry.

### Error handling reality

`ApiError` carries `status` and `detail`. But `client.ts:139` reads `body.detail` **only when
it is a string**:

```ts
if (typeof body.detail === "string") detail = body.detail;
```

The backend raises `HTTPException(status, "sentence")`, which is always a string — so this
works for deliberate errors. **FastAPI's 422 validation response is a list**, so every field
validation error falls through to `resp.statusText` and the user sees "Unprocessable Entity"
instead of what was wrong. See the gap below and `API` rules in §05.

### Server state

A single bare `new QueryClient()` in `main.tsx:9` — **no default options**. No `staleTime`, no
`retry` policy, no `refetchOnWindowFocus` override. Every behaviour is therefore per-call
default.

Practiced conventions:

- **Query keys are inline arrays**, never a centralized factory: `["my-readiness"]`,
  `["student-readiness", sid]`, `["topic-evidence", sid, selectedTopic]`,
  `["resources", g.id, "recording"]`.
- **`queryFn` is a bare reference** to an `api/` export, or a thin arrow closing over an id.
- **Async AI work is polled with a self-terminating `refetchInterval`** — the function form,
  which inspects the last result and returns `false` once settled. Used in `ReportsPanel.tsx`,
  `SubmitHomeworkPage.tsx`, `SitPastPaperPage.tsx`. Fixed-interval polling appears once:
  `ActivityMenu.tsx:29` at 120 seconds.
- **Mutations invalidate in `onSuccess`**, often several keys at once —
  `SubmitHomeworkPage.tsx:31–32` invalidates both `["my-submission", id]` and
  `["my-assignments"]`. There are **no optimistic updates** and no `setQueryData` anywhere.
- **`useQueries`** fans out over groups in `FilesPage.tsx` and `RecordingsPage.tsx`.
- **Auth is deliberately outside Query.** `AuthContext` is `useState` plus a `useEffect`
  calling `fetchMe()` once on mount, with `signIn`/`signOut` callbacks. `useAuth()` throws
  outside its provider.

### Types

Every `api/` module hand-writes TypeScript interfaces mirroring the backend's Pydantic
response shapes. **There is no OpenAPI codegen and no contract test**, though FastAPI
publishes a correct schema at `/docs` for free. A backend field rename type-checks cleanly on
both sides and fails at runtime as a blank field. This is `RISK-6`.

### Build and type configuration

- `npm run dev` — Vite on 5173, proxying `/api` to `localhost:8000` (`vite.config.ts`).
- `npm run build` — `tsc -b && vite build`. **This is the only type check that runs
  anywhere**; `vitest run` does not type-check.
- `tsconfig.json` is genuinely strict: `strict`, `noUnusedLocals`, `noUnusedParameters`,
  `noFallthroughCasesInSwitch`, `isolatedModules`, `noEmit`, ES2022, `moduleResolution:
  "bundler"`, `skipLibCheck`.
- **No ESLint and no Prettier.** `package.json` scripts are exactly `dev`, `build`, `preview`,
  `test`.

---

## Standards

### HTTP and data

**`FE-1` — MUST · Critical · Active**
Every HTTP call goes through `api<T>()` in `frontend/src/api/client.ts`. The only sanctioned
exceptions are `fetchFileUrl()` for blob downloads and `streamMessage()` for SSE, both of
which implement their own auth and refresh.
*Rationale:* bearer attachment, transparent refresh, and error normalization live there; a
raw `fetch` silently opts out of all three, and its 401s will log the user out.

**`FE-2` — MUST NOT · Critical · Active**
Never write `refresh_token` to `localStorage`, `sessionStorage`, IndexedDB, or any
script-readable store.
*Rationale:* it is a 30-day credential; the httpOnly cookie exists so that XSS costs 30
minutes instead. See `ADR-0008` and `SEC` rules in §07.

**`FE-3` — MUST · Important · Active**
A new endpoint gets a typed wrapper in the matching `frontend/src/api/<domain>.ts` module.
Components call the wrapper, never a path literal.
*Rationale:* path literals scattered through components make an API change an archaeology
exercise.

**`FE-4` — MUST · Critical · Active**
A change to a backend response schema updates the mirroring TypeScript interface in the same
pull request.
*Rationale:* nothing checks the two agree; this convention is the only control (`RISK-6`).

**`FE-5` — MUST NOT · Important · Active**
Never treat a `ProtectedRoute` role gate as a security control. It hides interface only.
*Rationale:* the client is fully under the user's control; authorization is the API's job.

### Server state

**`FE-6` — MUST · Important · Active**
Server data is held in TanStack Query, not copied into `useState`. Derive from the query
result; do not mirror it.
*Rationale:* a mirrored copy does not invalidate and will be stale after a mutation.

**`FE-7` — MUST · Important · Active**
Query keys include every input the query varies on — ids, filters, selections.
*Rationale:* a key missing an input serves one student's data under another's cache entry.

**`FE-8` — MUST · Important · Active**
A mutation invalidates every query key its write affects, in `onSuccess`.
*Rationale:* the only mechanism keeping the interface consistent, since there are no
optimistic updates.

**`FE-9` — SHOULD · Recommended · Active**
Poll asynchronous server work with the function form of `refetchInterval`, returning `false`
once the work has settled.
*Rationale:* the established pattern in three pages; a fixed interval polls forever and costs
requests after the answer has arrived.

**`FE-10` — SHOULD NOT · Recommended · Active**
Do not add a global state library. Server state belongs to Query, auth to `AuthContext`,
everything else to local `useState`.
*Rationale:* `governance/non-goals.md`; the product has no state that needs one.

### Structure

**`FE-11` — MUST · Important · Active**
A new page goes in the folder for the role that uses it, its route inside the matching
`ProtectedRoute` group, and — if top-level — an entry in that role's nav array.
*Rationale:* a route outside its guard is reachable by the wrong role; a page with no nav
entry is unreachable.

**`FE-12` — SHOULD · Recommended · Active**
A component used by two or more roles goes in `components/`; pure logic with no JSX goes in
`lib/`.
*Rationale:* `lib/readiness.ts` is the model — pure functions there are the only frontend code
currently unit-tested in isolation.

**`FE-13` — SHOULD · Recommended · Active**
Keep page components under roughly 300 lines. Beyond that, extract sections into siblings, as
`tutor/tabs/` and `tutor/today/` already do.
*Rationale:* the four largest pages are the hardest to change and the least tested.

### Interface behaviour

**`FE-14` — MUST · Important · Active**
Every query-backed surface handles loading, empty, error, and loaded explicitly.
*Rationale:* enforces `UX-23`; an unhandled empty state is where a fabricated zero appears.

**`FE-15` — MUST · Important · Active**
Render `ApiError.detail` when present, and never render a raw exception or stack to a user.
*Rationale:* the backend's message is written for the user; the fallback is not.

**`FE-16` — MUST · Important · Active**
File uploads send `FormData` and MUST NOT set `Content-Type` manually.
*Rationale:* the browser must add the multipart boundary; `api<T>()` already skips the header
for `FormData` bodies, and overriding it produces an unparseable request.

**`FE-17` — SHOULD · Recommended · Active**
Authenticated files are displayed via `fetchFileUrl()` and `URL.createObjectURL`, revoking the
object URL on unmount.
*Rationale:* an `<img src="/api/...">` sends no `Authorization` header; failing to revoke
leaks memory across navigations.

---

## Known Gaps

| Gap | Why it matters | Severity |
|---|---|---|
| **422 validation errors are discarded.** `client.ts:139` reads `detail` only when it is a string; FastAPI's validation `detail` is a list, so the user sees `resp.statusText`. | Every field-level validation failure surfaces as "Unprocessable Entity". Fixing it is one branch here plus the envelope work in §05. | `blocking` |
| **No OpenAPI codegen or contract test.** Response types are hand-mirrored. | A backend rename fails silently at runtime. `FE-4` is a convention with nothing enforcing it. `RISK-6`. | `blocking` |
| **`QueryClient` has no defaults.** No `staleTime`, no `retry` policy. | Refetch-heavy behaviour and inconsistent retry semantics across the app. See §10. | `before scale` |
| **No ESLint or Prettier.** | `FE-*` and §13 are enforced by review alone. Unused imports and hook-dependency mistakes are invisible. `RISK-2`. | `blocking` |
| **`vitest run` does not type-check.** Only `npm run build` does, and no automation runs it. | A type error reaches `main` unless someone builds locally. | `blocking` |
| **Auth state is a hand-rolled context** with a single `fetchMe()` on mount. | No refetch on focus and no cross-tab synchronization: signing out in one tab leaves another believing it is signed in until its next 401. | `nice to have` |
| **Four pages exceed 300 lines** and none is covered by a test. | The highest-change-risk files in the frontend are the least verified. | `before scale` |

---

## Review Triggers

Update this document when:

- `api/client.ts` changes — especially the refresh path, storage shape, or error parsing.
- A route group, role guard, or nav array changes in `App.tsx`.
- The `QueryClient` gains default options.
- OpenAPI codegen or a contract test is introduced.
- A linter, formatter, or type-check step is added.
- A new sanctioned bypass of `api<T>()` is created.
- `VITE_API_BASE_URL` or the same-origin proxy arrangement changes.
