# 12. Quality Engineering

> **Volume 4 — Reliability & Operations** · Engineering Constitution v1.2 · Status: Active
> **Owner:** Founder (see `governance/ownership.md`)
>
> Governs how a change is proven correct before it ships.

## Contents

- [Purpose](#purpose)
- [Scope](#scope)
- [Sources](#sources)
- [Principles](#principles)
- [Current Reality](#current-reality)
  - [The backend suite](#the-backend-suite)
  - [The test harness and its two traps](#the-test-harness-and-its-two-traps)
  - [Established testing patterns](#established-testing-patterns)
  - [The frontend suite](#the-frontend-suite)
  - [Static analysis](#static-analysis)
  - [What verifies a pull request](#what-verifies-a-pull-request)
- [Standards](#standards)
- [Known Gaps](#known-gaps)
- [Review Triggers](#review-triggers)

---

## Purpose

Avora has a substantial, fast, well-designed backend test suite, and since `ci.yml` landed it
runs on every pull request. This document records the harness and the patterns worth
following, defines what "done" means per change class, and states plainly what remains
unenforced: the rules below that CI cannot check are enforced by a human
remembering.

## Scope

**In scope:** test strategy and layering; the backend and frontend harnesses; established
patterns for jobs and AI paths; static analysis; the definition of done; the review checklist;
what must be tested per change class.

**Out of scope:** code style (§13); what to do when something breaks in production (§14);
performance measurement (§10).

### Non-goals

- **No end-to-end browser suite.** No Playwright, no Cypress. The manual pass in §14 covers
  the flows an e2e suite would.
- **No mocking of the database.** Tests run against real SQLite through the real ORM.
- **No calls to real AI providers in tests.** Every AI path is exercised through `fake_ai`.
- **No coverage percentage target.** Coverage of the marking, auth, and readiness paths matters;
  a repository-wide number does not, and optimizing one produces tests written for the metric.
- **No snapshot testing of rendered output.** Assert behaviour, not markup.

## Sources

Written from: `backend/tests/` (26 files); `backend/tests/conftest.py`;
`backend/pyproject.toml`; `backend/app/db.py`; `frontend/src/test/` (7 files);
`frontend/vite.config.ts`; `frontend/tsconfig.json`; `frontend/package.json`.

---

## Principles

**P1 — Tests run without infrastructure.** No database, no API key, no network. The backend
suite is one command from a clean checkout, and that is why it gets run.

**P2 — Test the behaviour, not the implementation.** Most backend tests drive the real HTTP
surface through `httpx` against the real app. They break when behaviour changes, which is what
a test is for.

**P3 — The riskiest code gets the most tests.** Marking, auth, and readiness carry the most
consequence and have the most coverage. That distribution is correct and should be preserved.

**P4 — A test that cannot fail is worse than no test.** It costs maintenance and buys
confidence it has not earned.

**P5 — Convention is not verification.** Every rule in this constitution that nothing checks is
enforced by a human remembering. Say so, rather than implying otherwise.

---

## Current Reality

### The backend suite

**45 files, ~12,300 lines. 527 tests pass** in about five and a half minutes with no database
and no API key.

Coverage is concentrated where the risk is:

| Area | Files | Notable |
|---|---|---|
| Homework and marking | `test_homework.py` (749 lines, 24 tests), `test_auto_marking.py` (563, 14) | The largest and most consequential |
| Past papers | `test_past_papers.py` (398, 16) | Exercises the polymorphic path |
| Security | `test_security_hardening.py` (370, 14) | Documented nowhere before this handbook |
| Readiness | `test_readiness_*.py` × 6 | Engine, factors, v2, AI, shadow, cutover |
| Classroom | `test_classroom.py` (362, 10) | Fully mocked Google API |
| Jobs | `test_jobs.py` (299, 9) | |
| Auth | `test_auth.py` (125, 16) | |
| Authorization | `test_authorization.py` (188, 37) | Route inventory + negative cases; fails if any route drops its gate |
| Health and worker | `test_health.py` (268, 13) | Liveness, readiness, worker supervision, retry backoff |

Note the earlier `handoff.md` recorded 215 tests; that document is archived rather than
corrected, with a header saying so. The suite reached 247 by the time this handbook was
written, 297 once the `RISK-4` and `RISK-7` fixes landed with their tests, and 527 through
tasks 0.6–0.10.

**Two of these files test properties rather than behaviour**, which is worth knowing before
editing them. `test_authorization.py` walks the app's route tree and asserts things *about the
shape of the API* — that exactly eight routes are reachable without a token, that role gates
are one shared dependency by identity, that no module has grown its own copy of the check. It
fails when someone adds an endpoint without a gate, which is the point; the fix is to add the
gate, or to add the route to `PUBLIC_ROUTES` deliberately. `test_health.py` likewise asserts
that a slow job is not mistaken for a dead worker.

### The test harness and its two traps

`backend/tests/conftest.py` sets four environment variables **before any app module is
imported** — `DATABASE_URL=sqlite+aiosqlite:///:memory:`, a test `JWT_SECRET`, a temporary
`UPLOAD_DIR`, and `REFRESH_COOKIE_SECURE=false`. The ordering is load-bearing: `app/db.py`
creates its engine at import time from `get_settings()`.

`db.py` supplies `StaticPool` and `check_same_thread: False` **only** for in-memory SQLite,
because each session would otherwise see an empty database.

Fixtures:

| Fixture | Purpose |
|---|---|
| `_db_schema` (autouse) | `Base.metadata.create_all` before each test, `drop_all` after |
| `_reset_login_limiter` (autouse) | Clears the process-global failed-login counter so one test's bad passwords do not leak into later tests |
| `client` | `httpx.AsyncClient` over `ASGITransport` — the real app, no network |
| `tutor` | A registered tutor plus ready-to-use auth headers |
| `fake_ai` | Factory for a `structured_complete` stand-in returning a normalized `AiResponse` |

**Trap 1 — a model missing from `models/__init__.py` silently gets no table.** The schema is
built from `Base.metadata`, which is populated by that barrel. The symptom is an
"unknown table" error far from the cause (`BE-3`).

**Trap 2 — the suite never executes a migration.** The schema comes from `create_all`, not
from Alembic, so nothing in `pytest` can tell you a migration works. CI's `migrations` job is
what covers that gap: `upgrade head` → `downgrade base` → `upgrade head` on a real
`postgres:16-alpine`, all 24 migrations, on every pull request. What it still cannot see is
**data** — the CI database is empty, and the container command in production is
`alembic upgrade head && uvicorn`, so a failure there means the service never starts.
Migration 0012 failed exactly that way on Postgres with existing users, which an empty-database
check would have passed.

This trap has a second edge documented in §06: **four of the five real indexes exist only in
migrations**, so the test schema is missing them and no test ever exercises an indexed plan.

### Established testing patterns

Two patterns are the house style and both are worth stating as rules.

**Drive jobs synchronously.** Tests call `process_one_job()` directly rather than running
`worker_loop()`:

```python
await client.post("/api/v1/assignments", ...)   # enqueues extract_assignment
await process_one_job()                          # runs it, deterministically
```

**Monkeypatch the calling module's name, not `services.ai`.** Because services import
`structured_complete` into their own namespace, patching the source module does nothing:

```python
monkeypatch.setattr("app.services.marking.structured_complete", fake_ai(result))
```

The `fake_ai` docstring says this explicitly. Getting it wrong produces a test that silently
makes a real network call — or, with no key configured, fails with `AIUnavailableError` from an
unexpected place.

### The frontend suite

**9 files, 49 tests.** `App.test.tsx` (1), `Nav.test.tsx` (2), `ClassroomSettings.test.tsx`
(3), `PastPapers.test.tsx` (4), `ReadinessView.test.tsx` (4), `TodayDashboard.test.tsx` (4),
`readiness-lib.test.ts` (5), `client-errors.test.ts` (17) and `contrast.test.ts` (9).

The test names are worth reading as a statement of intent: several assert the constitution's
own rules rather than mechanics — *"with no data it explains the empty state and invents no
scores"* (`PROD-2`), *"says the score is being recalculated rather than passing it off as
current"* (`UX-21`), *"explains itself instead of offering a dead button when unconfigured"*
(`INF-9`). This is the pattern to extend.

The two newest files extend it furthest, by asserting **properties of the product rather than
behaviour of a component**. `contrast.test.ts` parses the design tokens out of `index.css` and
recomputes every WCAG ratio, so `UX-8` and `UX-9` are checked arithmetic rather than a table
someone has to remember to update — and it pins the formula against black-on-white = 21:1,
because a contrast guard computing the wrong ratio guards nothing. `client-errors.test.ts`
covers the error parser and then stubs `fetch` to prove a real 422 reaches a caller readable,
on the principle that the parser being correct is not the fix.

Together with `test_authorization.py` on the backend, these are the tests that make a fixed
defect stay fixed. They fail on the class of mistake, not the instance of it.

Vitest is configured inline in `vite.config.ts`: `environment: "jsdom"`, `globals: true`, one
setup file importing `@testing-library/jest-dom/vitest`. No `include`/`exclude` patterns, no
coverage block.

**`vitest run` does not type-check.** The only type gate anywhere is `tsc -b` inside
`npm run build`, and no automation runs it.

Twenty tests against 60-plus pages is thin, and the four largest pages —
`AssignmentDetailPage`, `SubmissionReviewPage`, `SyllabusUploadPage`, `AssignmentCreatePage` —
have none.

### Static analysis

**Backend: ruff**, configured in `pyproject.toml` and run in CI as `ruff check` plus
`ruff format --check`. Rules are selected to catch defects rather than to enforce taste — a
broad selection reports 1,071 findings on this codebase and the configured one reports 57,
which is the difference between a gate someone clears and a number everybody learns to
ignore. `line-length = 100` because that is what the code already is (99th-percentile line:
99 characters). Every exclusion is argued at the site; the two that are substantive rather
than cosmetic are `UP042` (`(str, Enum)` → `StrEnum` changes `str(Member)` on enums that get
serialized) and `F811` in tests (pytest's fixture idiom is a redefinition by construction).

The `# noqa: BLE001` comments in `workers/jobs.py`, `api/chat.py`, `main.py` and
`readiness_v2_ai.py` are no longer vestigial: `BLE` is selected, so they suppress a rule that
actually runs, and the next blind `except Exception` is a decision on the record.

**Frontend: ESLint 9 (flat config) and Prettier**, run in CI as `eslint --max-warnings 0` and
`prettier --check`. ESLint adds only what types cannot see — `rules-of-hooks`,
`exhaustive-deps`, `no-unused-vars` — because `tsc -b` already covers the rest and a rule
that duplicates the type checker only adds a second place to silence the same thing. The
React Compiler rule set the plugin ships by default is deliberately not adopted: it is a
decision about how the app is written, not a lint baseline.

`tsconfig.json` is genuinely strict — `strict`, `noUnusedLocals`, `noUnusedParameters`,
`noFallthroughCasesInSwitch`, `isolatedModules` — and is now gated by a build CI runs on
every pull request.

**Both clean sets were verified rather than assumed.** A linter reporting nothing is
indistinguishable from a linter that is not running, so each rule was checked against a
planted violation: a conditionally-called hook, a dependency array missing its closure, an
unused argument, an unused local, an indented `def _require_tutor`. Each reported; each file
was then removed.

**Coverage:** not configured on either side. `.gitignore` lists `.coverage` and `htmlcov/`, but
nothing produces them.

### What verifies a pull request

`.github/workflows/ci.yml`, on every pull request and on every push to the default branch.
Four jobs:

| Job | Runs | Catches |
|---|---|---|
| `lint` | `ruff check`, `ruff format --check`, `mypy app/services app/schemas`, `eslint --max-warnings 0`, `prettier --check` | Style and correctness defects ruff and eslint see, and type errors in the two checked backend packages |
| `backend` | Python 3.11, `pip install -e ".[dev]"`, `pytest` from `backend/` | Every backend regression the suite covers. No service container — `conftest.py` forces in-memory SQLite |
| `migrations` | `postgres:16-alpine` service, then `alembic upgrade head` → `downgrade base` → `upgrade head` | A migration that is invalid or irreversible on Postgres. This is the only thing that has ever executed the downgrade path |
| `frontend` | Node 20, `npm ci`, `npm test`, the API-type regeneration diff, `npm run build` | Vitest regressions, generated types drifting from `openapi.json`, and — via `tsc -b` inside `build` — every frontend type error, which is the only type check the frontend has |

`concurrency` with `cancel-in-progress` means a force-push supersedes the previous run rather
than racing it.

**What CI does not do**, stated plainly because the gap is easy to mistake for coverage:

- **Python type checking covers two packages, not the backend.** `mypy app/services
  app/schemas` runs in the `lint` job (task 0.8); annotations in `app/api`, `app/models` and
  `app/workers` are still decoration nothing verifies. Widening it is a per-module ratchet —
  `[tool.mypy] packages` in `backend/pyproject.toml` and the CI step move together. This is
  now the whole of `RISK-2`.
- **No dependency scan**, which is not a theoretical gap: the first `npm audit` anyone ran
  reported a critical and a high advisory in `vitest` and `vite`. See `RISK-11`.
- **No coverage measurement**, so nothing reports which risky paths the 527 backend tests miss.
- **The `migrations` database is empty.** Schema operations are proven; safety against
  existing rows, which is how 0012 actually failed, is not.
- **No contract check between backend schemas and the frontend's per-domain wrappers.** The
  shared types in `api/client.ts` and `api/auth.ts` are generated from the app's own OpenAPI
  document and their freshness is gated — `tests/test_openapi_snapshot.py` for
  `openapi.json`, and a regenerate-and-diff step for `schema.d.ts`. The interfaces still
  declared by hand in the other `api/*.ts` modules are not (`RISK-6` residual).

`CLAUDE.md` also mentions CodeQL, Vercel preview builds, and CodeRabbit. Those are
GitHub-App-configured and may well run; **nothing in the repository evidences them**, so they
are not part of the gate this document describes. `RISK-2` is largely mitigated; the linting
half is what remains.

---

## Standards

### Strategy

**`QA-1` — MUST · Critical · Active**
The backend suite runs with no database, no API key, and no network, from a clean checkout.
*Rationale:* P1 — the reason this suite gets run is that running it costs nothing. Introducing
a service dependency would end that.

**`QA-2` — MUST · Important · Active**
Prefer testing behaviour through the real HTTP surface with the `client` fixture over testing
internals directly.
*Rationale:* P2 — a test coupled to an implementation detail blocks refactoring and does not
notice a behaviour change.

**`QA-3` — MUST · Important · Active**
Pure decision logic — scoring, factor math, grade mapping — is tested directly, without
fixtures.
*Rationale:* `BE-4` keeps that code pure precisely so it can be; `test_readiness_factors.py` is
the model.

**`QA-4` — MUST · Important · Active**
Every bug fix ships with a test that fails without the fix.
*Rationale:* P4 — otherwise there is no evidence the fix addresses the bug, and nothing stops
its return.

**`QA-5` — MUST NOT · Important · Active**
Never assert something that cannot fail — a mock returning what the test then checks, or an
assertion on a value the test itself set.
*Rationale:* it costs maintenance and buys confidence it has not earned. This has happened in
this repository before and was caught in review.

### Established patterns

**`QA-6` — MUST · Critical · Active**
Drive background jobs in tests by calling `process_one_job()`. Never start `worker_loop()`.
*Rationale:* the loop polls and is non-deterministic; `process_one_job()` makes the job's
execution an explicit, ordered step.

**`QA-7` — MUST · Critical · Active**
Stub AI calls by monkeypatching the **calling module's** name with the `fake_ai` fixture, not
`app.services.ai`.
*Rationale:* services import the helper into their own namespace, so patching the source module
does nothing and the test makes a real network call or fails from an unexpected place.

**`QA-8` — MUST NOT · Critical · Active**
Never call a real AI provider from a test.
*Rationale:* non-deterministic, slow, costs money, and breaks `QA-1`.

**`QA-9` — MUST · Important · Active**
A test that changes process-global state resets it, via an autouse fixture where the state is
shared.
*Rationale:* `_reset_login_limiter` exists because the failed-login counter is a module-level
dict; anything similar needs the same treatment.

### Per change class

**`QA-10` — MUST · Critical · Active**
A new model is re-exported from `models/__init__.py`, and a test touches it.
*Rationale:* Trap 1 — without the re-export it has no table in tests, and the failure appears
far from the cause.

**`QA-11` — MUST · Critical · Active**
A migration is verified `upgrade` → `downgrade` → `upgrade` before merge, and — where it alters
a populated table — against Postgres **with data**.
*Rationale:* Trap 2. The suite never runs migrations, and the failures that have occurred were
Postgres-specific. CI's `migrations` job now performs the up/down/up half automatically on
Postgres 16, which turns most of this rule from a request into a check. **The "with data" half
is still manual** — the CI database is empty — and it is the half that caught 0012 out.
`DB-16`, `DB-18`, `DB-19`.

**`QA-12` — MUST · Critical · Active**
A change touching authentication or authorization ships with a test asserting the **negative**
case: the wrong role, another organization's row, a revoked token.
*Rationale:* a positive-only test passes just as well against an endpoint with no check at all
— which, given `RISK-7`, is the failure mode to expect.

**`QA-13` — MUST · Important · Active**
A change to an AI surface tests the failure path as well as the success path: provider
unavailable, malformed output, low confidence.
*Rationale:* degradation is a feature here (§11), and an untested degradation path is an
assumption.

**`QA-14` — MUST · Important · Active**
A change to a job handler tests that running it twice on the same payload is safe.
*Rationale:* `BE-6`. Idempotency is a correctness requirement of at-least-once delivery, and it
is exactly the property that silently regresses.

**`QA-15` — SHOULD · Important · Active**
A change to a response schema regenerates `frontend/openapi.json` and `schema.d.ts`, and
exercises the endpoint.
*Rationale:* `API-15`, `FE-4`. Regeneration is enforced — `tests/test_openapi_snapshot.py`
fails on a stale snapshot and CI fails on stale generated types — but only the shapes already
aliased from `components["schemas"]` benefit; a hand-written interface still agrees with the
backend only because someone changed both (`RISK-6`).

**`QA-16` — SHOULD · Recommended · Active**
A new frontend page or shared component gets at least one test covering its primary state and
its empty state.
*Rationale:* the four largest pages have none, and they are the highest-change-risk files in
the frontend.

### Definition of done

**`QA-17` — MUST · Critical · Active**
A change is done when: both suites pass locally; `npm run build` type-checks if the frontend
changed; new behaviour has a test; migrations are verified up/down/up; the constitution
documents it contradicts are updated (`GOV-1`); and any rule it breaks is fixed, superseded, or
recorded as a gap (`GOV-3`).
*Rationale:* nothing automates any of this, so "done" has to be a written checklist rather than
a green tick.

**`QA-18` — MUST · Important · Active**
A pull request states what was verified and how, including anything checked manually.
*Rationale:* P5 — the review is the only verification checkpoint, and a reviewer cannot re-run
what they were not told about.

### Tooling

**`QA-19` — MUST · Critical · Active**
Continuous integration runs, on every pull request: the backend suite, the frontend suite,
`tsc -b`, and an Alembic up/down/up against Postgres. A change that removes or weakens a leg of
that gate is a constitutional change, not a workflow tweak.
*Rationale:* `RISK-2`. `main` deploys on merge, so an unverified merge is an unverified deploy.
Satisfied by `.github/workflows/ci.yml`.

**`QA-20` — SHOULD · Important · Active**
A linter and formatter run in CI for both languages — ruff for Python, ESLint and Prettier for
TypeScript.
*Rationale:* `CODE-*` in §13 is otherwise enforced entirely by review. Satisfied by the `lint`
job in `.github/workflows/ci.yml`. The rule sets are scoped to defects rather than taste, and
every exclusion is argued where it is configured — a suppression with a stated reason is a
decision, a suppression without one is a rule that will be deleted the first time it is
inconvenient.

**`QA-22` — SHOULD · Important · Draft**
A formatting-only change is committed on its own, never mixed into a substantive one.
*Rationale:* the reformatting pass that introduced ruff and Prettier touched 133 files across
both languages. Mixed into a real change, a diff that size is skimmed rather than read, and
the two lines that mattered ship unreviewed. **Draft** because it is a convention this
document can state but nothing can check — the reviewable form of it is that a
formatting-only commit is verifiable by re-running the tool, and the ruff pass was
additionally proved a no-op by comparing every file's AST before and after.

**`QA-21` — SHOULD · Recommended · Draft**
Coverage is measured and reported for `services/` and `api/`, without a repository-wide
percentage target.
*Rationale:* a number invites tests written for the number; a report on the risky modules
informs where to write real ones.

---

## Known Gaps

| Gap | Why it matters | Severity |
|---|---|---|
| **The type checker covers `services/` and `schemas/` only.** mypy runs on those two packages in CI (task 0.8); `api/`, `models/` and `workers/` are unchecked. | The layer with the decision math and the API contracts is verified; a wrong annotation in a router still only misleads a reader. This is what `RISK-2` still covers. Widen it a package at a time — one `packages` entry plus the CI step, fixing what it finds in the same PR. | `before scale` |
| **Nothing scans dependencies.** The first `npm audit` anyone ran reported 8 advisories — 1 critical (`vitest`), 1 high (`vite`), both needing a semver-major. | `RISK-11`'s stated trigger has fired. Both are dev-only and neither ships to a user, but the count grew unobserved for two majors, and an audit step in the existing `lint` job is the cheapest control in this document. | `blocking` |
| **CI's migration check runs against an empty database.** Up/down/up on Postgres 16 is automated; data safety is not. | It cannot catch the failure that has actually happened — 0012 added a non-nullable column to a populated table. `QA-11`'s "with data" clause and `DB-18` are manual compensating controls. `RISK-3` residual. | `before scale` |
| **The test suite itself still runs no migration.** Schema comes from `Base.metadata.create_all` on SQLite. | Model/migration drift is invisible to `pytest`; only the separate CI job would catch a migration that fails outright, and it would not catch one that merely disagrees with the models. | `before scale` |
| **`vitest run` does not type-check.** `npm run build` does, and CI runs it — but a developer running `npm test` locally still gets no type errors. | The strict `tsconfig.json` is now enforced on every PR; the local feedback loop still misses it, so type errors are found late rather than never. | `nice to have` |
| **The frontend suite is 49 tests against 60+ pages**, and the four largest pages still have none. | 26 of those 49 guard the design tokens and the error parser, which is real but is not page coverage. The highest-change-risk frontend files remain unverified. | `before scale` |
| **No coverage measurement.** `.gitignore` anticipates it; nothing produces it. | No signal on which risky paths are untested. Blocks `QA-21`. | `nice to have` |
| **The test schema differs from production** — four indexes exist only in migrations. | No test exercises an indexed query plan. §06, `DB-12`. | `before scale` |
| **The per-domain API wrappers still hand-mirror their payloads.** `client.ts` and `auth.ts` alias the generated schema; `homework.ts`, `readiness.ts` and the rest declare their own interfaces. | A field rename in one of those domains passes both suites and fails at runtime, exactly as before — the generated types close this only where they are used. Convert each domain as it is next touched. `RISK-6` residual. | `before scale` |
| **The manual verification script referenced by the archived handoff lives outside the repository.** | The one documented end-to-end pass is unrecoverable; §14's manual checks replace it. | `nice to have` |

---

## Review Triggers

Update this document when:

- mypy's package list widens, or a coverage tool is configured.
- A dependency scan is added to CI, or the `vite`/`vitest` advisories are resolved.
- `conftest.py`'s fixtures or environment setup change.
- The test database stops being SQLite, which retires Trap 2 and changes `QA-11`.
- A new established testing pattern emerges that others should follow.
- An escaped defect reveals a change class that needs a `QA-*` rule.
