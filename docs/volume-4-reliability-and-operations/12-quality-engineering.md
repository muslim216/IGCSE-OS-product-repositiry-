# 12. Quality Engineering

> **Volume 4 — Reliability & Operations** · Engineering Constitution v1.0 · Status: Active
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

MANARA has a substantial, fast, well-designed backend test suite and **nothing that runs it**.
This document records the harness and the patterns worth following, defines what "done" means
per change class, and states the gap plainly: every rule here is currently enforced by a human
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

**26 files, roughly 262 test functions, ~6,100 lines. 247 tests pass** in about three minutes
with no database and no API key.

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

Note the earlier `handoff.md` recorded 215 tests. The suite has grown to 247; that document is
archived rather than corrected, with a header saying so.

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

**Trap 2 — the migrations are never executed.** The schema comes from `create_all`, not from
Alembic. All 21 migrations run for the first time in production, where the container command is
`alembic upgrade head && uvicorn`, so a failure means the service never starts. Migration 0012
has already failed this way on Postgres with existing users.

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

**7 files, 23 tests, 528 lines.** `App.test.tsx` (1), `Nav.test.tsx` (2),
`ClassroomSettings.test.tsx` (3), `PastPapers.test.tsx` (4), `ReadinessView.test.tsx` (4),
`TodayDashboard.test.tsx` (4), and `readiness-lib.test.ts` (5) — the only pure-unit spec.

The test names are worth reading as a statement of intent: several assert the constitution's
own rules rather than mechanics — *"with no data it explains the empty state and invents no
scores"* (`PROD-2`), *"says the score is being recalculated rather than passing it off as
current"* (`UX-21`), *"explains itself instead of offering a dead button when unconfigured"*
(`INF-9`). This is the pattern to extend.

Vitest is configured inline in `vite.config.ts`: `environment: "jsdom"`, `globals: true`, one
setup file importing `@testing-library/jest-dom/vitest`. No `include`/`exclude` patterns, no
coverage block.

**`vitest run` does not type-check.** The only type gate anywhere is `tsc -b` inside
`npm run build`, and no automation runs it.

Twenty tests against 60-plus pages is thin, and the four largest pages —
`AssignmentDetailPage`, `SubmissionReviewPage`, `SyllabusUploadPage`, `AssignmentCreatePage` —
have none.

### Static analysis

**Backend: none.** No ruff, black, isort, flake8, mypy, pyright, or pre-commit.
`pyproject.toml` contains exactly two lines of tool configuration:

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

The `# noqa: BLE001` comments in `workers/jobs.py` and `api/chat.py` are vestigial — no linter
reads them.

**Frontend: no ESLint, no Prettier.** `package.json` scripts are exactly `dev`, `build`,
`preview`, `test`. `tsconfig.json` is genuinely strict — `strict`, `noUnusedLocals`,
`noUnusedParameters`, `noFallthroughCasesInSwitch`, `isolatedModules` — which is real value,
gated behind a build nothing runs automatically.

**Coverage:** not configured on either side. `.gitignore` lists `.coverage` and `htmlcov/`, but
nothing produces them.

### What verifies a pull request

**Nothing in this repository.** `.github/` has never existed on any branch — no test run, no
build, no lint, no type check, no migration check.

`CLAUDE.md` states that CI gates pull requests via CodeQL, Vercel preview builds, and
CodeRabbit. Those are GitHub-App-configured and may well run; **nothing in the repository
evidences it**, and a repository whose verification is invisible cannot be reasoned about. This
is `RISK-2`, the highest-priority entry in the register.

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
a populated table — against Postgres with data.
*Rationale:* Trap 2. The suite never runs migrations, and the failures that have occurred were
Postgres-specific. `DB-16`, `DB-19`.

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
A change to a response schema updates its TypeScript mirror and exercises the endpoint.
*Rationale:* `API-15`, `FE-4`. Nothing checks the two agree (`RISK-6`).

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

**`QA-19` — MUST · Critical · Draft**
Continuous integration runs, on every pull request: the backend suite, the frontend suite,
`tsc -b`, and an Alembic up/down/up against Postgres.
*Rationale:* `RISK-2`. `main` deploys on merge, so an unverified merge is an unverified deploy.
**Draft** because it requires adding `.github/workflows/`, which is a code change outside this
documentation branch.

**`QA-20` — SHOULD · Important · Draft**
A linter and formatter run in CI for both languages — ruff for Python, ESLint and Prettier for
TypeScript.
*Rationale:* `CODE-*` in §13 is otherwise enforced entirely by review. **Draft** — same reason.

**`QA-21` — SHOULD · Recommended · Draft**
Coverage is measured and reported for `services/` and `api/`, without a repository-wide
percentage target.
*Rationale:* a number invites tests written for the number; a report on the risky modules
informs where to write real ones.

---

## Known Gaps

| Gap | Why it matters | Severity |
|---|---|---|
| **Nothing verifies a pull request.** `.github/` has never existed. No test run, build, lint, type check, or migration check. | `main` deploys on merge, so an unverified merge is an unverified deploy. `RISK-2` — the highest-priority entry in the register. Blocks `QA-19`. | `blocking` |
| **Migrations are never exercised by tests.** Schema comes from `Base.metadata.create_all`. | All 21 run first in production, where failure means the service does not start. `RISK-3`. `QA-11` is a manual compensating control. | `blocking` |
| **No linter, formatter, or type checker on the backend.** `pyproject.toml` has two lines of pytest config. The `# noqa` comments are read by nothing. | Every §13 rule is enforced by review alone. Blocks `QA-20`. | `blocking` |
| **`vitest run` does not type-check**, and nothing runs `npm run build` automatically. | The strict `tsconfig.json` is real value gated behind a step nobody runs. | `blocking` |
| **The frontend suite is 23 tests against 60+ pages**, and the four largest pages have none. | The highest-change-risk frontend files are unverified. | `before scale` |
| **No coverage measurement.** `.gitignore` anticipates it; nothing produces it. | No signal on which risky paths are untested. Blocks `QA-21`. | `nice to have` |
| **The test schema differs from production** — four indexes exist only in migrations. | No test exercises an indexed query plan. §06, `DB-12`. | `before scale` |
| **No contract test between backend schemas and frontend types.** | A field rename passes both suites and fails at runtime. `RISK-6`. | `blocking` |
| **The manual verification script referenced by the archived handoff lives outside the repository.** | The one documented end-to-end pass is unrecoverable; §14's manual checks replace it. | `nice to have` |

---

## Review Triggers

Update this document when:

- CI is introduced — most Draft rules here become Active at once, and several `blocking` gaps
  close.
- A linter, formatter, type checker, or coverage tool is configured.
- `conftest.py`'s fixtures or environment setup change.
- The test database stops being SQLite, which retires Trap 2 and changes `QA-11`.
- A new established testing pattern emerges that others should follow.
- An escaped defect reveals a change class that needs a `QA-*` rule.
