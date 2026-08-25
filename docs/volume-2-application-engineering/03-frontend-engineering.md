# 03. Frontend Engineering

> **Volume 2 — Application Engineering** · Engineering Constitution v1.5 · Status: Active
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
storage, and the API types — generated from the backend's OpenAPI document where they are
shared, still hand-written in the per-domain wrappers.

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
  schedule | resources | analytics | new-homework | mock`.
- **Student** (`roles={["student"]}`): `/student` and its siblings. `/student/improvement`
  and `/student/tutor` still resolve — both redirect (to `/student/progress` and `/student`
  respectively) rather than 404 a bookmark — but neither is in `STUDENT_NAV` or routes to a
  live page; task 0.4 deleted `ImprovementPage.tsx` (AV-57, AV-100) and 0.3 deleted
  `TutorChatPage.tsx` (AV-57).
- **Parent** (`roles={["parent"]}`): `/parent`, with no nav array.
- **Catch-all:** `*` redirects to `/`.

Navigation is data-driven: `STUDENT_NAV` (7 entries, no bottom-slot item since 0.3 removed the
one that carried `slot: "bottom"`) and `TUTOR_NAV`, each `{ to, label, icon }` with
`lucide-react` icons.

**Route guards are a convenience, not a control.** `ProtectedRoute` hides interface; the API
enforces authorization. Never treat a role gate as a security boundary — see `SEC` rules in
§07.

### The API client

`frontend/src/api/client.ts` is the only place `fetch` is configured. `api<T>(path, options,
retry = true)`:

1. Reads the access token from `localStorage["avora-tokens"]` and sets
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

**One deliberate bypass** of `api<T>()` exists and is the only sanctioned one:

- `homework.ts:fetchFileUrl()` — fetches a file as a blob for `URL.createObjectURL`, because
  an authenticated file cannot be an `<img src>`.

(`chat.ts:streamMessage()` was the other bypass — Server-Sent Events, with its own
401-refresh-and-retry — until task 0.3 (AV-57) deleted the chat surface, `chat.ts` included.)

### Error handling reality

`ApiError` carries `status` and `detail`. But `client.ts:139` reads `body.detail` **only when
it is a string**:

```ts
const parsed = parseErrorBody(await resp.json());
if (parsed.detail) detail = parsed.detail;
fields = parsed.fields;
```

`parseErrorBody()` reads both shapes the API produces. A handler-raised
`HTTPException(status, "sentence")` gives a string and passes through unchanged. FastAPI's
schema validation gives `{"detail": [{loc, msg, type}, …]}`, which becomes
`"Target grade: Input should be a valid integer"` — the `loc` source prefix dropped because
the user did not choose it, and list indices rendered 1-based because someone counting
questions on screen starts at one.

`ApiError` carries the parsed `fields` alongside `message`, so a form can render them against
the offending inputs without another client change. **Every existing caller reads
`err.message` and needed no edit.**

When the body says nothing usable the detail stays empty and the caller falls back to
`resp.statusText`. That fallback is deliberate: an empty string presented as a message leaves
the user with a blank error box, which is worse than the "Unprocessable Entity" this replaced.
`API-11`, and `src/test/client-errors.test.ts`.

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

**The contract types are generated, not written** (task 0.8). `frontend/openapi.json` is the
app's own OpenAPI document, dumped from `app.openapi()`; `src/api/schema.d.ts` is
`npm run generate:api` (openapi-typescript) over it. `api/client.ts` and `api/auth.ts` alias
`components["schemas"][...]` — `User` is `UserOut`, `AuthResponse` is `AuthResponse`,
`TokenPair` is the server's `AccessToken`. A field renamed on a Pydantic model renames the
TypeScript type, and every stale use fails `tsc -b`.

Regenerate both files in the same PR as the backend change. Two checks enforce it:
`backend/tests/test_openapi_snapshot.py` fails when `openapi.json` no longer matches the
running app, and CI's frontend job regenerates `schema.d.ts` and fails on a diff. **Never
hand-edit either file** — both are `.prettierignore`d for the same reason.

**The per-domain wrappers are still hand-written.** `homework.ts`, `readiness.ts`,
`groups.ts` and the rest declare their own interfaces, and for those a backend rename
type-checks cleanly on both sides and fails at runtime as a blank field. That is what remains
of `RISK-6`; convert a domain to schema aliases when you next touch it.

### Build and type configuration

- `npm run dev` — Vite on 5173, proxying `/api` to `localhost:8000` (`vite.config.ts`).
- `npm run build` — `tsc -b && vite build`. **This is the only type check on the frontend**;
  `vitest run` does not type-check. CI's `frontend` job runs it, so a type error cannot reach
  the default branch unnoticed — but nothing runs it for you locally.
- `tsconfig.json` is genuinely strict: `strict`, `noUnusedLocals`, `noUnusedParameters`,
  `noFallthroughCasesInSwitch`, `isolatedModules`, `noEmit`, ES2022, `moduleResolution:
  "bundler"`, `skipLibCheck`.
- **ESLint and Prettier are both configured**, and CI runs both: `npm run lint` (`eslint .`,
  with `--max-warnings 0` in CI), `npm run format:check` (`prettier --check .`). `lint:fix`
  and `format` are the writing forms; CI never writes.
- `npm run generate:api` — `openapi-typescript openapi.json -o src/api/schema.d.ts`. CI
  regenerates and fails on a diff, which is what keeps the generated contract honest.

---

## Standards

### HTTP and data

**`FE-1` — MUST · Critical · Active**
Every HTTP call goes through `api<T>()` in `frontend/src/api/client.ts`. The only sanctioned
exception is `fetchFileUrl()` for blob downloads, which implements its own auth and refresh.
(`streamMessage()` for SSE was the other one until task 0.3 (AV-57) deleted the chat surface.)
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
A change to a backend response schema regenerates `openapi.json` and `schema.d.ts` in the
same pull request, and updates any interface still mirroring that shape by hand.
*Rationale:* regeneration is checked in CI, so a stale snapshot fails rather than drifts; the
hand-written wrappers have no such check and this convention is still their only control
(`RISK-6`).

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
| **`ApiError.fields` is populated and nothing renders it.** Forms show the joined `message` string, not per-field errors against the inputs. | The information now reaches the client and stops at the form. Rendering it is per-form work; the joined sentence is readable in the meantime, so this is an improvement left on the table rather than a defect. `API-11`. | `nice to have` |
| **Codegen covers the shared contract types only.** `client.ts` and `auth.ts` alias the generated schema; every per-domain wrapper still hand-writes its interfaces. | A backend rename in an unconverted domain still fails silently at runtime — the generator closed the gap where it is used, not everywhere. `RISK-6` residual. | `before scale` |
| **`QueryClient` has no defaults.** No `staleTime`, no `retry` policy. | Refetch-heavy behaviour and inconsistent retry semantics across the app. See §10. | `before scale` |
| **`vitest run` does not type-check.** Only `npm run build` does; CI's `frontend` job runs it, so a type error cannot reach the default branch unnoticed. | The local loop still misses it: `npm test` passing is not evidence the branch compiles. Run `npm run build` before opening a PR. | `nice to have` |
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
