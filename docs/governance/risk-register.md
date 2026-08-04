# Architectural Risk Register

> **Governance layer.** Standing architectural risks, their likelihood, impact, and
> mitigation.
>
> **Status:** Active · Part of Engineering Constitution v1.0
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

**Likelihood:** High · **Impact:** High · **Priority:** P1 · **Owner:** Founder

`.github/` has never existed on any branch. No test run, build, lint, type check, or
migration check happens on a pull request. The backend has no linter, formatter, or type
checker configured at all; the frontend's only static gate is `tsc -b` inside
`npm run build`, which no automation runs.

`CLAUDE.md` states that CI gates pull requests via CodeQL, Vercel preview builds, and
CodeRabbit. Those are GitHub-App-configured and may well run — but nothing in the repository
proves it, and a repository whose verification is invisible cannot be reasoned about.

**Trigger:** already materialized. A regression reaching `main` undetected is a matter of
time, and `main` deploys immediately on merge.

**Mitigation:** add `.github/workflows/` running pytest, vitest, `tsc -b`, and an
Alembic up/down/up check. Add ruff and eslint. This is a code change requiring its own pull
request; it is recorded as a `blocking` gap in §12 and §13.

**Not accepted.** This is the highest-priority item in the register.

---

## RISK-3 — Migrations are validated only by production

**Likelihood:** Medium · **Impact:** Severe · **Priority:** P1 · **Owner:** Founder

`backend/tests/conftest.py` builds the schema from `Base.metadata.create_all`, not from
Alembic. All 21 migrations are therefore exercised for the first time when a container
starts in production — and the container start command is
`alembic upgrade head && uvicorn`, so **a failing migration means the service never
starts**, taking the whole API down rather than degrading.

This has already bitten once: migration 0012 failed on Postgres with existing users, fixed
in a follow-up.

**Trigger:** any migration touching an existing table with data.

**Mitigation:** run `alembic upgrade head` / `downgrade` / `upgrade` against a real Postgres
in CI, ideally seeded. Partially mitigated today by the convention of verifying up/down/up
on SQLite by hand — which does not catch Postgres-specific failures, which is exactly the
class that has occurred.

---

## RISK-4 — A dead worker is silent

**Likelihood:** Medium · **Impact:** High · **Priority:** P1 · **Owner:** Founder

The worker is an asyncio task in the API process. If it dies, the API keeps serving requests
and `GET /api/v1/health` keeps returning `{"status": "ok"}` — the health endpoint is a
static literal that checks nothing, and `render.yaml` does not even declare a
`healthCheckPath`.

Meanwhile extraction, marking, readiness synthesis, reports, and Classroom sync all stop.
The user-visible symptom is homework that is "processing" forever.

Compounding it: a job that fails twice is marked failed and nothing announces it. There is
no alert, no dead-letter queue, and no metric.

**Trigger:** unhandled exception escaping `worker_loop`; process restart under load; a
poisoned job.

**Mitigation:** health check that verifies the database and the worker's liveness;
`healthCheckPath` set in `render.yaml`; alerting on failed-job count and on queue age. None
done. See §11.

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

**Likelihood:** Medium · **Impact:** Severe · **Priority:** P1 · **Owner:** Founder

`api/deps.py` defines `require_role(*roles)`, `get_current_org_id()` and `CurrentOrg`. **None
of the three is called anywhere.** Authorization is instead 10 hand-copied
`def _require_tutor(user)` functions plus one `_require_student`, invoked imperatively inside
handler bodies, with organization scoping applied ad hoc per query.

Eleven copies of an authorization check are eleven places to forget one. A new router that
omits the call has no role check at all, and nothing — no test, no linter, no type error —
notices.

**Trigger:** a new router, or a new endpoint on an existing router.

**Mitigation:** converge on the dependency, which enforces the check at the signature rather
than in the body. Recorded as a gap in §04 and §07.

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

| ID | Risk | L | I | P |
|---|---|---|---|---|
| RISK-2 | Nothing automated verifies any change | High | High | **P1** |
| RISK-3 | Migrations validated only by production | Med | Severe | **P1** |
| RISK-4 | A dead worker is silent | Med | High | **P1** |
| RISK-7 | Authorization duplicated eleven times | Med | Severe | **P1** |
| RISK-1 | Single-instance with no scale-out path | Med | High | P2 |
| RISK-5 | Two readiness engines can disagree | High | Med | P2 |
| RISK-6 | Frontend/backend contracts drift silently | High | Med | P2 |
| RISK-8 | Uploads on a disk with no backup story | Med | Severe | P2 |
| RISK-9 | Minors' data with no formal policy | Med | Severe | P2 |
| RISK-11 | Dependencies unpinned and unscanned | Med | High | P2 |
| RISK-10 | Prompt changes have no regression net | Med | Med | P3 |
| RISK-12 | AI cost model is unbounded | Med | Med | P3 |

## Review triggers

- Quarterly review, per the change process.
- A risk's trigger is observed — re-rank immediately, do not wait for the quarter.
- An incident occurs: add the risk it revealed, or record why an existing entry did not
  predict it.
- A mitigation ships: move the entry to accepted-and-watched, or close it.
- A non-goal is reversed, which usually retires or creates a risk.
