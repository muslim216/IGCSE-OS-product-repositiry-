# Architectural Risk Register

> **Governance layer.** Standing architectural risks, their likelihood, impact, and
> mitigation.
>
> **Status:** Active · Part of Engineering Constitution v1.2
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
| **Priority** | P1 (act now) / P2 (planned) / P3 (accepted, watched) |
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
workers are safe), move the rate limiter to Postgres or Redis. **None is done.** The job
queue's locking is the one part already built for it.

**Accepted because:** current volume is a single tutor's practice. The cost of the migration
is bounded and the trigger is observable.

---

## RISK-2 — Nothing automated verifies any change

**Likelihood:** Low · **Impact:** High · **Priority:** P3 (residual) · **Owner:** Founder

**Largely mitigated.** `.github/workflows/ci.yml` now runs on every pull request: `pytest`,
`vitest`, `npm run build` (which is `tsc -b && vite build`, the only type check anywhere),
and an Alembic `upgrade head` → `downgrade base` → `upgrade head` against Postgres 16.

Until then `.github/` had never existed on any branch, and `CLAUDE.md` stated that CI gated
pull requests via CodeQL, Vercel preview builds and CodeRabbit. Those are GitHub-App
configured and may well run, but nothing in the repository proved it. Both claims are now
corrected.

**Residual:** no linter, formatter or Python type checker is configured — no ruff, black,
isort, mypy, or eslint. Every `CODE-*` style rule and every Python type annotation is still
enforced by review alone. Adding them was deliberately excluded from the CI change so the
gate would not arrive buried in a formatting diff across ~22k lines.

**Trigger:** a style or typing regression merging unnoticed; or CI being disabled, made
non-blocking, or its jobs allowed to stay red.

**Mitigation:** done for correctness, outstanding for style. Recorded in §12 and §13.

**Not accepted.** This is the highest-priority item in the register.

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

**Likelihood:** High · **Impact:** Medium · **Priority:** P2 · **Owner:** Founder

`frontend/src/api/*.ts` hand-mirrors the backend's Pydantic response shapes as TypeScript
interfaces. There is no OpenAPI codegen and no contract test, although FastAPI generates a
correct schema at `/docs` for free.

A backend field rename type-checks fine on both sides and fails at runtime, in production,
as a blank field.

**Trigger:** any change to a Pydantic response model.

**Mitigation:** generate types from the OpenAPI schema, or add a contract test comparing
them. Today the only control is `FE-*` in §03 requiring both sides to change in one pull
request — a convention, not a check.

---

## RISK-7 — Authorization logic is duplicated eleven times

**Likelihood:** Low · **Impact:** Severe · **Priority:** P3 (residual) · **Owner:** Founder

**Closed for role checks.** Every route now takes `user: TutorUser` or `user: StudentUser`
from `api/deps.py` — 38 tutor-gated routes and 13 student-gated, out of 125. All eleven
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

MANARA stores named children's academic records, parent contact details, images of student
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

**Likelihood:** Medium · **Impact:** High · **Priority:** P2 · **Owner:** Founder

`backend/Dockerfile` runs `pip install .` against the `>=` ranges in `pyproject.toml` with no
lockfile, so two builds of the same commit can produce different dependency trees. The image
runs as root. There is no `.dockerignore`. Nothing scans dependencies for known
vulnerabilities.

**Trigger:** an upstream release breaking a build that previously worked; a published CVE in
a transitive dependency.

**Mitigation:** lockfile, non-root user, `.dockerignore`, and a vulnerability scan. See §08
and §07.

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
| RISK-5 | Two readiness engines can disagree | High | Med | P2 | highest-ranked open risk |
| RISK-6 | Frontend/backend contracts drift silently | High | Med | P2 | `tsc -b` now runs in CI, but nothing compares the two sides |
| RISK-1 | Single-instance with no scale-out path | Med | High | P2 | |
| RISK-3 | Migrations validated only by production | Low | Severe | P2 | up/down/up in CI; database not seeded |
| RISK-4 | A dead worker is silent | Low | Med | P2 | detected and supervised; nothing alerts |
| RISK-8 | Uploads on a disk with no backup story | Med | Severe | P2 | |
| RISK-9 | Minors' data with no formal policy | Med | Severe | P2 | |
| RISK-11 | Dependencies unpinned and unscanned | Med | High | P2 | |
| RISK-2 | Nothing automated verifies any change | Low | High | P3 | tests, types and migrations gated; no linter |
| RISK-7 | Authorization duplicated eleven times | Low | Severe | P3 | role checks closed; org scoping still per query |
| RISK-10 | Prompt changes have no regression net | Med | Med | P3 | |
| RISK-12 | AI cost model is unbounded | Med | Med | P3 | |

**No entry is currently ranked P1.** All four that were — `RISK-2`, `RISK-3`, `RISK-4`,
`RISK-7` — have shipped mitigations and been re-ranked against their residuals.

The highest-ranked open item is now `RISK-5`: readiness v1 and v2 coexisting, with
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
