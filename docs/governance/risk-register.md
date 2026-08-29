# Architectural Risk Register

> **Governance layer.** Standing architectural risks, their likelihood, impact, and
> mitigation.
>
> **Status:** Active · Part of Engineering Constitution v1.5
>
> **Review cadence:** quarterly, per `governance/change-process.md`.

## Purpose

Known Gaps and architectural risks are related but not the same thing, and conflating them
loses both.

- A **gap** is something missing or wrong *now*. It has a fix. It lives in the affected
  document's Known Gaps section.
- A **risk** is a way the system could fail *later*. It may have no fix — only a mitigation,
  a trigger to watch, and a decision about whether to accept it.

A gap can be closed. A risk is accepted, mitigated, or transferred, and then reviewed again.

## How to read an entry

| Field | Meaning |
|---|---|
| **Likelihood** | Low / Medium / High — chance of materializing within roughly 12 months at current trajectory |
| **Impact** | Low / Medium / High / Severe — consequence if it does |
| **Priority** | P1 (act now) / P2 (planned) / P3 (accepted, watched) / P4 (residual — mitigated, what's left is small enough to watch rather than plan) |
| **Trigger** | The observable event that means this risk is materializing |
| **Mitigation** | What reduces likelihood or impact, and whether it is done |
| **Owner** | Who watches it — see `governance/ownership.md` |

---

## RISK-1 — Single-instance architecture has no scale-out path

**Likelihood:** Medium · **Impact:** High · **Priority:** P2 · **Owner:** Founder

Three independent constraints pin the API to exactly one instance, and they will break
simultaneously:

1. `render.yaml` mounts a persistent disk for uploads, and a Render service with a disk runs
   one instance. `services/storage.py` writes to local disk.
2. The background job worker runs **inside the API process**, started in `main.py`'s
   `lifespan`.
3. `services/rate_limit.py` is a process-global dict; with two instances, the login throttle
   becomes per-instance and its effective limit doubles.

**Trigger:** sustained CPU or memory pressure on the single Render instance; or a
requirement for zero-downtime deploys; or worker backlog that a single process cannot clear.

**Mitigation:** the ordered sequence is documented in §08 — move storage to S3, move the
worker to its own service (the job table already uses `FOR UPDATE SKIP LOCKED`, so multiple
workers are safe), move the rate limiter to Redis. **All three are now built and none is
switched on** (Phase 1, `AV-82`: tasks 1.2, 1.3, 1.4). `STORAGE_BACKEND` still defaults to
`local`, `RUN_WORKER_IN_API` still defaults `True`, and `REDIS_URL` is unset in `render.yaml`.

That is the intended state, not an unfinished one. `AV-85` is explicit that Phase 1 builds
capability and the deployment stays at one instance until the Phase 11 concurrency audit
(11.2), because the two-instance correctness suite (1.5) covers the known cases rather than
every read-modify-write in the codebase. **Flipping any of these three without 11.2 is the risk
this entry describes, not its mitigation.**

**Accepted because:** current volume is a single tutor's practice. The cost of the migration
is bounded and the trigger is observable.

---

## RISK-2 — Nothing automated verifies any change

**Likelihood:** Low · **Impact:** Medium · **Priority:** P4 (residual) · **Owner:** Founder

**Mitigated.** `.github/workflows/ci.yml` runs on every pull request in four jobs: `ruff
check` + `ruff format --check`, `mypy app/services app/schemas`, `eslint --max-warnings 0`
and `prettier --check`; `pytest`; `vitest`, the API-type freshness check and
`npm run build` (which is `tsc -b && vite build`, the only frontend type check); and an
Alembic `upgrade head` → `downgrade base` → `upgrade head` against Postgres 16.

Until then `.github/` had never existed on any branch, and `CLAUDE.md` stated that CI gated
pull requests via CodeQL, Vercel preview builds and CodeRabbit. Those are GitHub-App
configured and may well run, but nothing in the repository proved it. Both claims are now
corrected.

The static-analysis job closed the residual that the first CI change deliberately left
open. Both rule sets are scoped to catch defects rather than enforce taste — the argued
exclusions are in `backend/pyproject.toml` and `frontend/eslint.config.js`, and each one
says why at the site rather than being silently absent. The two that are substantive rather
than cosmetic: `UP042` is off because `(str, Enum)` → `StrEnum` changes `str(Member)` on
serialized enums, and `react-refresh` is not installed because its only rule would have
split six files of correctly co-located code.

**Residual:** the Python type checker covers part of the backend, and less of it is
undeclared than the explicit `packages = ["app.services", "app.schemas"]` list suggests.
mypy's default `follow_imports=normal` checks every module those two packages import, and
`app/models` (the barrel nearly every service imports) and `app/workers/jobs.py` (imported
for `enqueue`) both come along for free — verified in practice, just not declared. `app/api`,
`app/security.py` and `app/main.py` are genuinely unchecked: nothing in `app/services` or
`app/schemas` imports any of them (`BE-1` keeps the routers and the entrypoint from being
imported by a lower layer), so a wrong annotation in a router, `security.py`, or `main.py`
still misleads a reader with nothing to catch it. That is the whole of what is left of this
risk.

**Trigger:** a typing regression merging unnoticed; or CI being disabled, made
non-blocking, or its jobs allowed to stay red.

**Mitigation:** done for correctness and style, and for types in `services/` and
`schemas/` — which, transitively, is most of `models/` and `workers/` too. Declaring
`app.api`, `app.security` and `app.main` explicitly is the remaining ratchet — but not all
under the same key: `packages` recurses into a package's submodules, which is what `app.api`
is; `app.security` and `app.main` are standalone modules with no `__init__.py` and nothing to
recurse into, so `[tool.mypy] modules` is the key that names them for what they are. Add both
keys to `backend/pyproject.toml` and the CI step together, and fix what they find in that PR
rather than adding a suppression. `ignore_missing_imports = true` is already set, so the cost
is those modules' own annotations, not their dependencies'.
Recorded in §12 and §13.

**Accepted for now**, at P4. No longer the highest-priority item in the register.

---

## RISK-3 — Migrations are validated only by production

**Likelihood:** Low · **Impact:** Severe · **Priority:** P2 (residual) · **Owner:** Founder

**Largely mitigated.** CI's `migrations` job runs `upgrade head` → `downgrade base` →
`upgrade head` against a real `postgres:16-alpine` on every pull request. The first full
run of that cycle was clean: all 21 upgrades and all 21 downgrades succeeded, and
`downgrade base` left only `alembic_version` behind — so `DB-16` holds, having previously
been verified only by hand and only on SQLite.

`backend/tests/conftest.py` still builds its schema from `Base.metadata.create_all` rather
than Alembic, and that is not changing: the suite wants a fast in-memory database, and
migration correctness is a different question answered by a different job. Before CI, the
21 migrations first executed when a container booted in production — where the start command
is `alembic upgrade head && uvicorn`, so **a failing migration means the service never
starts**, taking the whole API down rather than degrading. Migration 0012 did exactly that
once, on Postgres, with existing users.

**Residual:** CI runs against an *empty* database. A migration that succeeds on empty tables
and fails on production data — which is what 0012 was — would still pass. Seeding the
migration job is the remaining work.

**Trigger:** any migration that backfills, adds a NOT NULL column to a populated table, or
changes a constraint on existing rows.

**Mitigation:** partly done. Seed the CI database before the upgrade leg to close the rest.

---

## RISK-4 — A dead worker is silent

**Likelihood:** Low · **Impact:** Medium · **Priority:** P2 (residual) · **Owner:** Founder

**Largely mitigated**, in three parts:

1. The worker no longer dies unnoticed. `_supervised_worker()` in `main.py` restarts
   `worker_loop` on any exception *and* on a clean return, logging at error level. Previously
   `lifespan` created the task and never looked at it again.
2. `GET /api/v1/health/ready` reports the worker's state, the database, and the queue's
   pending/running/failed counts, returning 503 when the database is unreachable or the
   worker has stopped turning. `GET /api/v1/health` stays a shallow literal on purpose —
   it is what `healthCheckPath` polls, and a database round-trip there would turn a blip
   into a restart loop.
3. `render.yaml` now sets `healthCheckPath: /api/v1/health`. Render previously never probed
   the service at all, so a deploy was marked live without one successful request.

**Residual, and it is the important half: nothing announces any of this.** Readiness tells
the truth to whoever asks, and nobody is asking. There is no alerting, no dead-letter queue
and no metric, so a job that fails twice is still recorded and forgotten. Uptime monitoring
pointed at `/api/v1/health/ready` would close it; that needs a service the platform does not
have.

**Trigger:** a failed job count that nobody notices; a stalled queue discovered by a student
rather than by the system.

**Mitigation:** detection done, notification outstanding. See §11.

---

## RISK-5 — Two readiness engines can disagree

**Likelihood:** High · **Impact:** Medium · **Priority:** P2 · **Owner:** Founder

`/readiness/*` serves v2 snapshots with per-subject fallback to v1. But `api/analytics.py`,
`services/reports.py` and `services/student_crm.py` still read the v1 tables directly.

A tutor can therefore see one readiness number on the readiness page and a different number
for the same student in a report or on the CRM record. Both are "correct" — they come from
different engines — which makes the discrepancy hard to diagnose and corrosive to trust in
the metric.

**Trigger:** already materialized wherever a student has a v2 snapshot that differs from
their v1 topic readiness.

**Mitigation:** complete the cutover — repoint the three remaining readers, then drop
`topic_readiness`, `readiness_history`, and `tutor_preferences`. Deliberately deferred as its
own workstream.

---

## RISK-6 — Frontend and backend contracts drift silently

**Likelihood:** Low · **Impact:** Medium · **Priority:** P4 (residual) · **Owner:** Founder

**Closed for the shared contract types, 23 Aug (task 0.8).** `frontend/openapi.json` is
dumped from the app's own OpenAPI document and `frontend/src/api/schema.d.ts` is generated
from it by `npm run generate:api`; `api/client.ts` and `api/auth.ts` alias
`components["schemas"][...]` rather than restating the shapes. A field renamed on a Pydantic
model now renames the TypeScript type, and every use of the old name fails `tsc -b`.

Generated files close nothing while they go stale, so two checks keep them current:
`backend/tests/test_openapi_snapshot.py` fails when `openapi.json` no longer matches the
running app, and CI's frontend job regenerates `schema.d.ts` and fails on any diff. The first
commit of this work proved the point, and the shape of the mistake is the argument. The alias
read `components["schemas"]["TokenPair"]`. `TokenPair` is a real backend class — but its
docstring says "never sent to a client as JSON", because `SEC-2` put the refresh token in an
httpOnly cookie and left `AccessToken` as the only response body. A model nothing returns
never becomes an OpenAPI component, so the name exists in the server's source and not in its
contract. Mirroring by hand, that is precisely the name you would copy. `npm test` does not
type-check, so nothing local caught it: `tsc -b` in CI did.

**Residual:** the aliasing is not yet exhaustive. The per-domain wrappers under
`frontend/src/api/` still declare their own interfaces for many payloads; each one converted
is a shape that can no longer drift, and until then `FE-4` — both sides change in one PR —
is the only control over those.

**Trigger:** a response model changing while a hand-written interface still mirrors it; or
either generated file being edited by hand instead of regenerated.

**Mitigation:** convert the remaining hand-written interfaces to schema aliases as each
domain is next touched. Never hand-edit `openapi.json` or `schema.d.ts`.

---

## RISK-7 — Authorization logic is duplicated eleven times

**Likelihood:** Low · **Impact:** Severe · **Priority:** P3 (residual) · **Owner:** Founder

**Closed for role checks.** Every route now takes `user: TutorUser` or `user: StudentUser`
from `api/deps.py` — 45 tutor-gated routes and 14 student-gated, out of 135. All eleven
private helpers are deleted, and the seven ownership helpers below the routing layer call the
shared `assert_tutor()` rather than re-writing the condition.

Previously `require_role`, `get_current_org_id` and `CurrentOrg` were all defined and none
called; what ran was ten byte-identical `_require_tutor` copies plus one `_require_student`,
invoked in 35 handler bodies. The duplication was never the real problem — the location was.
A check in the body fails **open** when omitted; a check in the signature cannot be omitted.

`tests/test_authorization.py` is what keeps it closed: it asserts the exact set of eight
routes reachable without a token, that no module defines a private `_require_*` again, and
that the wrong role is refused on sixteen endpoints. Both regressions were confirmed to
actually fail the suite before the tests were trusted.

**Residual:** `get_current_org_id` and `CurrentOrg` are still unused. Organization scoping is
applied per query against `user.organization_id` — which satisfies `SEC-7`, but by convention
rather than by construction, so `PROD-4` remains enforced by memory in every query. That is
the same class of risk one layer down, and it is tracked in §01's Known Gaps.

**Trigger:** a query over a tenant-scoped table that forgets its organization filter.

**Mitigation:** role checks done. Org scoping unaddressed.

---

## RISK-8 — Uploads live on a disk with no backup story

**Likelihood:** Medium · **Impact:** Severe · **Priority:** P2 · **Owner:** Founder

Booklets, mark schemes, and student submissions are files on a 10 GB Render disk; the
database stores only relative paths. There is no documented backup of that disk, no
restore procedure, and no reconciliation between rows and files.

A deploy without the disk mounted orphans every row. A disk loss destroys every piece of
student work ever submitted, with the database still confidently referencing it.

**Trigger:** disk full (10 GB, no monitoring); disk loss; a deploy misconfiguration.

**Mitigation:** move to object storage — which `services/storage.py` was designed for, since
paths are stored relative — and back it up. Until then, disk usage should be watched
manually. See §14 for the disk-full runbook.

---

## RISK-9 — The product handles minors' data with no formal policy

**Likelihood:** Medium · **Impact:** Severe · **Priority:** P2 · **Owner:** Founder

Avora stores named children's academic records, parent contact details, images of student
handwriting, and encrypted Google refresh tokens. There is no data classification, no
retention policy, no deletion path, no data-processing agreement, and no stated legal basis.

The engineering controls are genuinely good — httpOnly refresh cookies, token revocation,
per-identifier throttling, magic-byte upload validation, single-use parent invites. The
governance around them does not exist.

**Trigger:** a customer asking a due-diligence question; a subject-access or deletion
request; operating in a jurisdiction with a children's-data regime.

**Mitigation:** §07 now defines a data classification and the handling rules per class.
Retention, deletion, and legal basis remain open.

---

## RISK-10 — Prompt changes have no regression safety net

**Likelihood:** Medium · **Impact:** Medium · **Priority:** P3 · **Owner:** Founder

Prompts are versioned in `services/prompts.py` and their version is stamped on every record
they produce — genuinely good traceability. But nothing evaluates whether a prompt change
makes marking *better or worse*. Tests use the `fake_ai` fixture and never exercise a real
model.

Because a scheme-backed, confident mark auto-finalizes with no human in the loop, a prompt
regression silently changes marks that count.

**Trigger:** any prompt edit; any model change, including a provider's silent update behind
a floating model alias.

**Mitigation:** a small golden set of marked questions with known-correct outcomes, run
against the real provider before a prompt or model change ships. See §09.

---

## RISK-11 — Dependencies are unpinned and unscanned

**Likelihood:** High · **Impact:** High · **Priority:** P1 · **Owner:** Founder

`backend/Dockerfile` runs `pip install .` against the `>=` ranges in `pyproject.toml` with no
lockfile, so two builds of the same commit can produce different dependency trees. The image
runs as root. There is no `.dockerignore`. Nothing scans dependencies for known
vulnerabilities.

**Trigger:** an upstream release breaking a build that previously worked; a published CVE in
a transitive dependency.

**The trigger has fired.** Running `npm audit` for the first time — incidentally, while
adding eslint, which is how nobody had run it before — reports **8 advisories on the
frontend: 1 critical, 1 high, 6 moderate.** Both serious ones are in the test and build
toolchain and both need a major upgrade:

| Package | Severity | Vulnerable | Fix |
|---|---|---|---|
| `vitest` | Critical | `<=3.2.5` (repo has `^2.0.5`) | `4.1.10`, semver-major |
| `vite` | High | `<=6.4.2` (repo has `^5.4.0`) | `8.2.0`, semver-major |

Both are `devDependencies`, and Vercel serves a static build, so neither ships to a user —
the exposure is a developer running the dev server or the vitest UI, and CI running
untrusted PR code. That bounds the blast radius; it does not make the finding stale, and
the numbers are two majors behind on each.

Deliberately **not** fixed in the lint change that found them: a `vite` and `vitest` double
major is a real upgrade with its own regression surface across 49 frontend tests and the
Tailwind v4 plugin, and burying it inside a formatting pass is exactly the pattern the split
commits there exist to avoid.

**Mitigation:** lockfile, non-root user, `.dockerignore`, and a vulnerability scan. The
scan is the cheapest of the four and now has a demonstrated hit rate — an `npm audit` and
`pip-audit` step in the CI lint job would have caught this two majors ago. Next: upgrade
`vite`/`vitest` on their own branch, then add the audit step so the count cannot climb
again unobserved. See §08 and §07.

---

## RISK-12 — The AI cost model is unbounded

**Likelihood:** Medium · **Impact:** Medium · **Priority:** P3 · **Owner:** Founder

Every AI call is metered into `ai_usage_events`, and `enqueue_readiness_v2_debounced()`
collapses bursts into one synthesis call — both good. But there is **no enforcement**: no
per-tutor allowance, no cap, no circuit breaker. `AI_MODEL_PRICING` is `{}` by default, so
until real prices are configured the reported spend is `unpriced_call_count` rather than a
number anyone can act on.

A large classified with hundreds of questions, or a burst of submissions, spends whatever it
spends.

**Trigger:** a bill larger than expected; a tutor bulk-uploading a year of work.

**Mitigation:** configure `AI_MODEL_PRICING`; then add per-organization budgets and a
breaker. The metering foundation is deliberately built for exactly this.

---

## Summary

| ID | Risk | L | I | P | Note |
|---|---|---|---|---|---|
| RISK-11 | Dependencies unpinned and unscanned | High | High | P1 | **trigger fired** — 1 critical + 1 high advisory, both dev-only, both needing a major |
| RISK-5 | Two readiness engines can disagree | High | Med | P2 | highest-ranked *unfired* risk |
| RISK-6 | Frontend/backend contracts drift silently | Low | Med | P4 | closed for the shared contract types — generated from OpenAPI and checked fresh in CI; per-domain wrappers still hand-written |
| RISK-1 | Single-instance with no scale-out path | Med | High | P2 | |
| RISK-3 | Migrations validated only by production | Low | Severe | P2 | up/down/up in CI; database not seeded |
| RISK-4 | A dead worker is silent | Low | Med | P2 | detected and supervised; nothing alerts |
| RISK-8 | Uploads on a disk with no backup story | Med | Severe | P2 | |
| RISK-9 | Minors' data with no formal policy | Med | Severe | P2 | |
| RISK-7 | Authorization duplicated eleven times | Low | Severe | P3 | role checks closed; org scoping still per query |
| RISK-10 | Prompt changes have no regression net | Med | Med | P3 | |
| RISK-12 | AI cost model is unbounded | Med | Med | P3 | |
| RISK-2 | Nothing automated verifies any change | Low | Med | P4 | lint, tests, types and migrations all gated; mypy's declared scope is `services/`/`schemas/`, but transitively covers most of `models/`/`workers/` too — `api/`, `security.py` and `main.py` are the real gap |

**One entry is ranked P1: `RISK-11`.** It is the only one in the register whose stated
trigger has actually fired rather than being anticipated — `npm audit`, run for the first
time, reports a critical and a high advisory in the frontend toolchain. It is ranked above
the P2 entries despite being dev-only exposure because it is the difference between a risk
we are watching and a finding we are holding.

The four that were previously P1 — `RISK-2`, `RISK-3`, `RISK-4`, `RISK-7` — have all shipped
mitigations and been re-ranked against their residuals. `RISK-2` has since dropped again to
P4, its residual now narrowed to the packages mypy does not yet cover. `RISK-6` joins them:
task 0.8 generated the frontend's contract types from the backend's own OpenAPI document and
gated both generated files in CI, dropping it from P2 to P4 on the shapes that were
converted.

The highest-ranked item with no realised failure behind it is `RISK-5`: readiness v1 and v2
coexisting, with
`analytics.py`, `reports.py` and `student_crm.py` still reading v1 tables directly while
`/readiness/*` serves v2, so two screens can show a student different numbers. Nothing about
it has changed — it is simply what is left. **It is left at P2 rather than promoted**, because
re-ranking an untouched risk is a judgement for the quarterly review and its owner, not a
side effect of other work landing.

## Review triggers

- Quarterly review, per the change process.
- A risk's trigger is observed — re-rank immediately, do not wait for the quarter.
- An incident occurs: add the risk it revealed, or record why an existing entry did not
  predict it.
- A mitigation ships: move the entry to accepted-and-watched, or close it.
- A non-goal is reversed, which usually retires or creates a risk.
