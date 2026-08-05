# 05. API Standards

> **Volume 2 — Application Engineering** · Engineering Constitution v1.2 · Status: Active
> **Owner:** Founder (see `governance/ownership.md`)
>
> Governs the HTTP contract: resource naming, methods and status codes, error shapes,
> pagination, versioning, and authorization at the endpoint boundary.

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

Twenty-three routers were written without a written contract, and it shows in small
divergences: three routers carry no prefix, two share one, response construction is done two
different ways, and there is no pagination anywhere. This document records what the API
actually does and fixes the contract for what comes next.

## Scope

**In scope:** URL and resource naming; HTTP methods and status codes; request and response
shapes; the error contract; pagination; versioning and deprecation; schema naming and
construction; file upload and download; Server-Sent Events; authorization at the endpoint
boundary.

**Out of scope:** the layering behind a router (§04); schema and persistence (§06); auth
token semantics and the threat model (§07); the frontend consuming it (§03).

### Non-goals

- **No GraphQL.** One versioned REST surface.
- **No API for third parties.** Every endpoint exists to serve MANARA's own clients; there is
  no public contract, no API keys, and no rate plan.
- **No HATEOAS.** Responses carry data, not link relations.
- **No `PATCH` semantics via JSON Patch.** Partial updates use a `XUpdate` schema with
  optional fields.
- **No breaking changes inside `/api/v1`.** See `API-16`.

## Sources

Written from: all 23 routers in `backend/app/api/`; `backend/app/api/deps.py`;
`backend/app/main.py`; the 17 modules in `backend/app/schemas/`;
`frontend/src/api/client.ts`.

---

## Principles

**P1 — The endpoint is the security boundary.** The client is under the user's control.
Every authorization decision happens here or below, never in the interface.

**P2 — Errors are for the person reading them.** A message is written for the user who will
see it, and a code is written for the client that must branch on it.

**P3 — A response shape is a contract.** It is hand-mirrored in TypeScript with nothing
checking the two agree, so changing one is changing both.

**P4 — Consistency beats individual elegance.** A convention followed everywhere is worth
more than a better convention followed in half the routers.

---

## Current Reality

### Versioning and mounting

One version. `main.py` mounts all 23 routers with `app.include_router(router,
prefix="/api/v1")` in a single loop, so **no router hardcodes the version**. Health is the
exception: `GET /api/v1/health` is defined inline on the app, returning a static
`{"status": "ok"}`.

### Naming as practiced

- **Kebab-case for multi-word resources**: `/ai-usage`, `/past-papers`, `/syllabus-uploads`,
  `/submissions/review-queue`, `/assignments/{id}/retry-extraction`,
  `/assignments/{id}/my-submission`, `/classroom/auth-url`.
- **snake_case for path and query parameters**: `{student_id}`, `subject_id`, `group_by`.
- **Collections registered as `@router.get("")`** — an empty string, so the prefix is the full
  path and there is no trailing slash.
- **Tags** match the router name.

**Three routers deliberately carry no prefix** because their routes span several resource
roots:

| Router | Roots it serves |
|---|---|
| `assessments.py` | `/assessments`, `/me/assessments`, `/observations`, `/students/{id}/observations` |
| `resources.py` | `/groups/{id}/resources`, `/resources/{id}` |
| `submissions.py` | `/submissions/…`, `/assignments/{id}/submissions`, `/me/assignments` |

**Two routers share the `/readiness` prefix** — `readiness.py` and `readiness_weights.py` —
and both use the `readiness` tag. They do not collide on paths (`/weights` is literal), but
the arrangement means `/readiness` is owned by two files, and `readiness_v2.py` adds a third
under `/readiness/v2`.

### Errors

**There are zero custom exception handlers.** `main.py` registers no `@app.exception_handler`
and no `RequestValidationError` override. Everything is FastAPI's default:

- `HTTPException(status, "message")` → `{"detail": "message"}`. The detail is **always a plain
  string** in this codebase; never a dict or list.
- Body validation failures → FastAPI's default 422 `{"detail": [{loc, msg, type}, …]}`.

There is **no error code, no envelope, and no correlation id**.

Status-code usage across `api/*.py`:

| Code | Count | Used for |
|---|---|---|
| 404 | 79 | Not found, and not-visible-to-you |
| 403 | 49 | Role or ownership failure |
| 201 | 29 | Creation |
| 409 | 19 | Conflict — duplicate enrolment, already submitted |
| 422 | 16 | Explicitly raised semantic validation |
| 204 | 13 | Deletion |
| 401 | 9 | Authentication (all from `deps.py`) |
| 503 | 4 | AI or Classroom not configured |
| 429 | 2 | Login throttle, daily chat cap |
| 400 | 1 | — |
| 202 | 1 | — |

**The frontend reads both shapes.** `parseErrorBody()` in `frontend/src/api/client.ts`
handles the string a handler raises and the `[{loc, msg, type}]` list schema validation
produces, turning the latter into `"Target grade: Input should be a valid integer"` and
exposing the parsed entries as `ApiError.fields`. It previously accepted only the string, so
**every 422 in the product reached the user as the bare HTTP status text** — the single most
user-visible consequence of having no error contract, and the reason `API-11` exists.

The contract itself is still FastAPI's default rather than anything this API declares. What
changed is that the client no longer discards half of it.

### Pagination

**None, anywhere.** All 29 `response_model=list[...]` endpoints return the complete result
set. There are no `limit`, `offset`, `page`, or `cursor` parameters on any endpoint.

The only query parameters in the entire API are filters: `subject_id` (assessments,
classifieds, knowledge, past-papers), `kind` (resources), `student_id` (reports — **required**,
not optional), and `group_by: Literal["feature","month","provider"]` on `/ai-usage/analytics`,
which is the only use of `fastapi.Query` in the codebase.

At current volume this is fine. The endpoints that will break first are the evidence and
usage lists, which grow monotonically.

### Schemas

One module per domain in `app/schemas/`, imported directly by routers. **`schemas/__init__.py`
is empty** — there is no barrel, unlike `models/__init__.py`.

Naming as practiced:

| Suffix | Meaning | Examples |
|---|---|---|
| `XCreate` | Creation body | `GroupCreate`, `AssignmentCreate`, `LessonCreate`, `RemarkRequestCreate` |
| `XUpdate` | Partial update body | `GroupUpdate`, `StudentProfileUpdate`, `MarkUpdate`, `ReadinessWeightsUpdate` |
| `XOut` | Standard response (~30 classes) | `SubjectOut`, `LessonOut`, `ReportOut` |
| `XDetail` | Richer variant, sometimes subclassing `XOut` | `PastPaperDetail(PastPaperOut)`, `AssignmentDetail`, `StudentCrmOut` |
| `XIn` | Nested input item | `QuestionIn`, `AssessmentScoreIn`, `GradeBoundaryIn` |
| `XSummary` | Compact list item or base class | `SubmissionSummary`, `GroupSummary`, `AiUsageSummary` |

Off-convention names exist and are worth knowing rather than pretending away: `SendMessage`,
`ReportGenerate`, `JoinRequest`, `LoginRequest`, `TutorSignupRequest`,
`StudentRegisterRequest`, `ParentRegisterRequest`, `ClassroomConnect`, `RefreshRequest`.

**Response construction is done two ways.** `model_config = ConfigDict(from_attributes=True)`
appears on only **8 classes** across 3 files. Everywhere else the router hand-constructs the
response field by field, usually through a module-local `_out(row)` or `_detail(row)` helper —
the pattern in `reports.py`, `resources.py`, `preferences.py`, `knowledge.py`,
`readiness_weights.py`, `syllabus_uploads.py`, `assignments.py`, and `past_papers.py`.

Validation is inline `Field(...)` constraints: `password: str = Field(min_length=8,
max_length=128)`, `username: str = Field(min_length=3, max_length=64,
pattern=r"^[a-zA-Z0-9_.-]+$")`, `content: str = Field(min_length=1, max_length=4000)`. There
is exactly one `field_validator` in the codebase, and it is in `config.py`, not a schema.

### Handler shape

All handlers are `async def` with the parameter order `(path params, body, db: DbSession,
user: CurrentUser)`.

A role gate is declared in the signature — `user: TutorUser` or `user: StudentUser` in place
of `user: CurrentUser` — so the parameter order above becomes `(path params, body, db, user)`
with the gate carried by the annotation. Ownership is then checked per query in the body. The
imperative `_require_tutor(user)` call this replaced is gone from all 23 routers; see §04,
`BE-17` and `RISK-7`.

### Uploads, downloads, and streaming

- **Uploads** use `File(...)` / `Form(...)` multipart in `assignments.py`, `classifieds.py`,
  `past_papers.py`, `resources.py`, `syllabus_uploads.py`, `submissions.py`.
- **Downloads** return `FileResponse` with the stored MIME type.
- **One streaming endpoint**: `POST /api/v1/chat/conversations/{id}/messages` returns
  `StreamingResponse(media_type="text/event-stream")` with
  `Cache-Control: no-cache` and `X-Accel-Buffering: no`, emitting hand-written SSE frames
  (`data:`, `event: error`, `event: done`) parsed by `frontend/src/api/chat.ts`.

### Response headers

A single `@app.middleware("http")` sets `X-Content-Type-Options: nosniff`,
`X-Frame-Options: DENY`, `Content-Security-Policy: default-src 'none'; frame-ancestors
'none'`, and `Referrer-Policy: no-referrer` via `setdefault`. The CSP is skipped for
`DOCS_PATHS = {"/docs", "/redoc", "/docs/oauth2-redirect"}`, because Swagger UI loads its
assets from a CDN. CORS comes from `settings.cors_origin_list` with `allow_credentials=True`.

### The polymorphic-submission trap

`Submission` is polymorphic: exactly one of `assignment_id` or `past_paper_id` is set
(`ADR-0004`). **A past-paper submission has `assignment_id = None`**, so code reading it
unconditionally raises — and in this codebase the place that mattered was inside an
authorization check. `_tutor_owns()` in `api/submissions.py` is the one place that branch is
allowed to live.

---

## Standards

### Naming and shape

**`API-1` — MUST · Important · Active**
Resources are plural, lowercase, kebab-case for multi-word names. Path and query parameters
are snake_case.
*Rationale:* matches the existing surface; a mixed convention makes URLs unguessable.

**`API-2` — MUST · Important · Active**
Collection routes are registered as `@router.get("")` so the router prefix is the full path.
No trailing slashes.
*Rationale:* FastAPI redirects trailing-slash mismatches, and a redirect drops the
`Authorization` header in some clients.

**`API-3` — SHOULD · Recommended · Active**
A router owns one resource root and declares its own prefix. Multi-root routers are permitted
only where the routes are genuinely one domain, as in `submissions.py`.
*Rationale:* three prefix-less routers already make "where does this endpoint live" a search
rather than a lookup.

**`API-4` — MUST · Important · Active**
Sub-resources nest under their parent (`/groups/{id}/resources`); actions on a resource are a
verb segment (`/assignments/{id}/retry-extraction`).
*Rationale:* the established pattern, and it keeps ownership checks structurally obvious.

### Methods and status codes

**`API-5` — MUST · Important · Active**
Use the method for the semantics: `GET` never mutates; `POST` creates or acts; `PUT`/`PATCH`
update; `DELETE` removes.
*Rationale:* a mutating `GET` will be retried, prefetched, or cached by something.

**`API-6` — MUST · Important · Active**
Status codes follow the table below.
*Rationale:* the codebase already follows it; writing it down is what keeps a new endpoint
from inventing a ninth meaning for 400.

| Situation | Code |
|---|---|
| Success with body | 200 |
| Resource created | 201 |
| Accepted for async processing | 202 |
| Success, no body | 204 |
| Malformed request | 400 |
| Not authenticated | 401 |
| Authenticated but not permitted | 403 |
| Not found, or not visible to this caller | 404 |
| State conflict | 409 |
| Semantically invalid | 422 |
| Rate limited | 429 |
| Dependency unavailable or not configured | 503 |

**`API-7` — MUST · Critical · Active**
Return `404`, not `403`, when a caller may not know a resource exists — including any resource
belonging to another organization.
*Rationale:* a `403` confirms existence. Integer primary keys are enumerable
(`governance/non-goals.md`), so a distinguishable `403` is an enumeration oracle across
tenants.

### Errors

**`API-8` — MUST · Important · Active**
Raise `HTTPException(status, "message")` with a message written for the person who will read
it: what happened, and what to do.
*Rationale:* `client.ts` renders `detail` directly to the user; an internal phrase reaches
them verbatim.

**`API-9` — MUST NOT · Critical · Active**
Never include a stack trace, SQL, internal path, or provider error verbatim in a response
body.
*Rationale:* it leaks implementation detail to an untrusted client and means nothing to the
reader.

**`API-10` — SHOULD · Important · Draft**
New error responses use the envelope `{"detail": str, "code": str}`, where `code` is a stable
machine-readable slug.
*Rationale:* clients currently branch on HTTP status alone, which cannot distinguish two 409s.
**Draft** because adding `code` is additive and safe, but it is only worth adopting alongside
the 422 fix and a client change — see Known Gaps.

**`API-11` — MUST · Important · Active**
Validation failures return field-level detail the client can render against the offending
input, and the client renders it rather than discarding it.
*Rationale:* FastAPI already produces this and `client.ts` used to discard it, so users saw
"Unprocessable Entity" for every field mistake in the product. Promoted from Draft when
`parseErrorBody()` landed; `src/test/client-errors.test.ts` covers the parser and stubs fetch
to prove a real 422 arrives readable. A handler that hand-rolls its own validation message
should still prefer a schema constraint, so the detail is produced in the standard shape —
see `API-16`.

### Pagination and collections

**`API-12` — MUST · Important · Active**
A collection that can grow without bound — evidence, usage events, messages, audit rows — is
paginated from its first version.
*Rationale:* retrofitting pagination is a breaking change for every existing client.

**`API-13` — SHOULD · Important · Active**
Pagination is `limit` (default 50, max 200) plus an opaque `cursor`, returning
`{"items": [...], "next_cursor": str | null}`.
*Rationale:* cursor paging is stable under concurrent inserts, which offset paging is not —
and these collections are append-heavy.

**`API-14` — SHOULD · Recommended · Active**
Collections have a deterministic sort order, stated in the endpoint's docstring.
*Rationale:* an unordered collection is unpaginatable and untestable.

### Contracts and versioning

**`API-15` — MUST · Critical · Active**
A change to a response schema updates the mirroring TypeScript interface in
`frontend/src/api/` in the same pull request.
*Rationale:* nothing checks the two agree (`RISK-6`); this convention is the only control.
Same rule as `FE-4`, stated from both sides deliberately.

**`API-16` — MUST NOT · Critical · Active**
Never make a breaking change inside `/api/v1`. Removing a field, renaming one, narrowing a
type, tightening validation, or changing a status code for an unchanged condition are all
breaking.
*Rationale:* the frontend is deployed independently of the API, so the two are never updated
atomically — there is always a window where old clients call new servers.

**`API-17` — SHOULD · Important · Active**
Deprecate before removing: mark the endpoint deprecated in its OpenAPI metadata, ship the
replacement, migrate the client, then remove after at least one release.
*Rationale:* `API-16` means removal is the only breaking change that is ever safe, and only
once nothing calls it.

**`API-18` — MUST · Important · Active**
Every endpoint declares an explicit `response_model`.
*Rationale:* it is the contract, it generates the OpenAPI schema, and it prevents a field
being returned by accident.

### Authorization

**`API-19` — MUST · Critical · Active**
Every endpoint that is not deliberately public enforces a role check **and** an ownership or
organization check. Being authenticated is never sufficient.
*Rationale:* role says what kind of user; ownership says which rows. Both are required, and
`PROD-4` depends on it.

**`API-20` — MUST · Critical · Active**
Never read `Submission.assignment_id` unconditionally. A past-paper submission has it as
`None`. Ownership branching for submissions lives only in `_tutor_owns()` in
`api/submissions.py`.
*Rationale:* it raises inside an authorization check, turning a null-handling bug into an
availability failure on a security path (`ADR-0004`).

**`API-21` — MUST · Important · Active**
Resource visibility for students is scoped to (organization, subject) derived from the groups
they belong to — never subject alone.
*Rationale:* subjects are global across organizations, so scoping by subject leaks every
tutor's material to every student. `_enrolled_scope` in `api/past_papers.py` is the reference
implementation.

### Requests and payloads

**`API-22` — MUST · Important · Active**
Validate at the schema boundary with `Field(...)` constraints — lengths, patterns, ranges,
`EmailStr` — rather than in the handler body.
*Rationale:* schema validation produces a 422 with field detail; a handler check produces
prose nobody can localize or map to an input.

**`API-23` — MUST · Important · Active**
Uploads are validated by magic bytes, not the client's `Content-Type`, through
`services/storage.py`.
*Rationale:* `Content-Type` is attacker-controlled. See `SEC` rules in §07.

**`API-24` — SHOULD · Recommended · Active**
Long-running work returns `202` with a resource whose status can be polled, rather than
blocking.
*Rationale:* the established pattern — extraction, marking, reports, and readiness all enqueue
a job and let the client poll.

**`API-25` — SHOULD · Recommended · Active**
Prefer `from_attributes=True` on response schemas over hand-built `_out(row)` helpers in new
code.
*Rationale:* a hand-built response silently omits a newly added field; both patterns exist
today, and the declarative one fails less quietly.

---

## Known Gaps

| Gap | Why it matters | Severity |
|---|---|---|
| **The 422 body is FastAPI's default, not a declared contract.** The client parses it, but nothing pins its shape; a FastAPI upgrade that changed `loc`/`msg` would break the parser silently on the server side. | The user-visible half is fixed and tested. The contract half is not: `API-10`'s error envelope is still Draft, and without it clients branch on HTTP status alone. | `before scale` |
| **No error codes.** Clients branch on HTTP status alone and cannot distinguish two 409s. | `API-10` is Draft for this reason; without codes, error handling is string-matching or nothing. | `before scale` |
| **No pagination on any of the 29 list endpoints.** | Evidence, usage events, and messages grow monotonically; the first to exceed a page of memory or a request timeout will do so in production. `API-12` binds new endpoints only. | `before scale` |
| **No correlation id on any response.** | A user-reported error cannot be tied to a log line. See §11. | `before scale` |
| **`/readiness` is owned by three routers** (`readiness.py`, `readiness_weights.py`, `readiness_v2.py`), two sharing a tag. | Violates `API-3`. No functional collision, but the OpenAPI grouping is misleading and "where is this endpoint" needs a search. | `nice to have` |
| **Response construction is inconsistent** — 8 classes use `from_attributes`, the rest hand-build via `_out(row)`. | A new model field is silently absent from hand-built responses. `API-25` binds new code only. | `nice to have` |
| **No rate limiting except on login and chat.** | Every other endpoint, including AI-triggering ones, is unbounded per user. See §07 and §10. | `before scale` |
| **The two health endpoints are not in a router.** `GET /api/v1/health` and `GET /api/v1/health/ready` are declared directly on the app in `main.py`. | Noted here because they are the only endpoints outside every convention in this document — no router, no tag, no `response_model`. That is deliberate for liveness (§11 explains why it must do no I/O), incidental for readiness. | `nice to have` |

---

## Review Triggers

Update this document when:

- A router is added, or a prefix or tag changes.
- An exception handler or error envelope is introduced.
- Pagination is added to any endpoint.
- `/api/v2` is contemplated.
- The status-code table in `API-6` gains a case.
- `client.ts` error parsing changes.
- A new content type — streaming, upload, or download — is introduced.
