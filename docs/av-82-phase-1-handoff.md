# Phase 1 (AV-82, Scale foundation) — agent handoff

**Audience: agents, not humans.** Dense and declarative on purpose. Assertions here are either
(a) verified in-session and marked `VERIFIED`, or (b) sourced to a file path or rule ID. Anything
unverified is marked `UNVERIFIED`. Do not upgrade an `UNVERIFIED` claim without testing it.

| Field | Value |
|---|---|
| Phase | 1 — Scale foundation (`AV-82`) |
| Spec of record | `docs/avora-new-state-august-16.md` §"Phase 1 — Scale foundation" (~lines 937–1045) |
| State as of | commit `67c9b0c` on the default branch (`claude/igcse-os-planning-q8be0t`) |
| Handoff written | 2026-08-28 |
| Migration head | `0027_worker_heartbeats` |
| Tasks done | 1.1, 1.2, 1.3 |
| Tasks remaining | **1.4** (next, unblocked), **1.5** (last, gated on 1.2–1.4) |

---

## 1. Task status

| ID | Task | Status | PR | Landed in |
|---|---|---|---|---|
| 1.1 | Architecture-impact report | **DONE** | #52 | `docs/av-82-architecture-impact-report.md` |
| 1.2 | Object storage | **DONE** | #53 | `app/services/storage.py`, `app/api/file_responses.py` |
| 1.3 | Worker as a separate process | **DONE** | #54 | `app/workers/*`, `app/models/workers.py`, migration `0027` |
| 1.4 | Shared rate limiting on Redis | **NOT STARTED** | — | — |
| 1.5 | Two-instance correctness suite | **NOT STARTED** | — | blocked on 1.4 |

Per the spec's dependency column, 1.4 depends only on 1.1 and is therefore unblocked. 1.5
requires 1.2–1.4 complete.

---

## 2. The single most important distinction

**Capability was built. Deployment was deliberately not changed.**

`AV-85` is explicit: build multi-instance capability in Phase 1, keep running **one** instance
until the Phase 11 concurrency audit (11.2). The two-instance suite (1.5) covers known cases,
not every read-modify-write in the codebase.

Production reality — `VERIFIED` against the live API on 2026-08-28:

| Fact | Value | Source |
|---|---|---|
| API instances | 1 | `render.yaml` — one `type: web`, no worker service |
| Worker | in-process | `run_worker_in_api` defaults `True` (`backend/app/config.py:145`) |
| Storage backend | `local` | `storage_backend` defaults `"local"` (`backend/app/config.py:120`) |
| Liveness | `200` | `GET /api/v1/health` |
| Readiness | `status: ok`, worker `running` | `GET /api/v1/health/ready` |
| Migration `0027` | applied | readiness reads `worker_heartbeats` and answers |

**DO NOT**, as part of 1.4 or 1.5: deploy a second instance, add a worker service to
`render.yaml`, or set `RUN_WORKER_IN_API=false`. That is Phase 11 work and 11.2 gates it.

---

## 3. Invariants established this phase — do not regress

Each of these was a real bug caught and fixed. Re-introducing one is a regression, not a style
choice.

### 3.1 Health must never answer "no idea" with a healthy state

`worker_status()` (`backend/app/workers/jobs.py`) returns `state="unknown"` when the heartbeat
table cannot be read. `unknown.healthy is False`. `not_started.healthy is True` — no worker
registered is the normal state under the test client, which never runs lifespan.

`VERIFIED`: `unknown healthy=False`, `not_started healthy=True`.

**DO NOT** collapse a read failure into `not_started`. That returns `200` from `/health/ready`
for a database the endpoint could not read.

### 3.2 Both readiness database reads are bounded

`_queue_snapshot()` and `_worker_snapshot()` in `backend/app/main.py` are each wrapped in
`asyncio.wait_for(..., timeout=READINESS_DB_TIMEOUT_SECONDS)`. Two separate reads, so one bound
does not cover the other: an exhausted pool sails past the first timeout and hangs in the second.

### 3.3 A reaped worker must come back, not vanish

`register_worker()` reaps a mid-job heartbeat row once `job_started_at` is older than
`HEARTBEAT_REAP_SECONDS`, because a job in flight that long cannot be distinguished from a
process that died holding one. That reap can hit a **live** worker — another worker starting is
enough.

`_write_heartbeat()` therefore sets `_worker_registered = False` and logs
`worker heartbeat row disappeared; will re-register` when its row is missing, handing recovery to
the retry `worker_loop()` already has.

**DO NOT** restore `if row is None: return` as a silent no-op. That leaves a process claiming and
running jobs while absent from every health answer — the invisible-worker failure (`RISK-4`) this
table exists to end, re-entered through its own cleanup path.

`VERIFIED` end to end; covered by
`backend/tests/test_health.py::test_a_worker_whose_row_was_reaped_re_registers`.

### 3.4 The reap predicate

`VERIFIED` against a real schema, not by reading the SQL:

| Row | `job_started_at` | `last_loop_at` | Outcome |
|---|---|---|---|
| idle, stale | `NULL` | > reap window | reaped |
| idle, fresh | `NULL` | recent | kept |
| live, long job | recent | > reap window | **kept** |
| dead mid-job | > reap window | > reap window | reaped |

Residual, accepted: a job legitimately running longer than `HEARTBEAT_REAP_SECONDS` loses its
`stalled` signal. Tolerated because nothing legitimately holds a job that long, and
`worker_status()` reports the healthiest row.

### 3.5 Test teardown must never drop a real schema

`TEST_DATABASE_URL` sets `DATABASE_URL` **process-wide**. `backend/tests/conftest.py`'s
`_db_schema` teardown is guarded by `_USING_THROWAWAY_SQLITE`, so `drop_all` only ever runs
against in-memory SQLite. `backend/tests/test_worker_concurrency.py` shadows that fixture
module-scoped and **does not drop** either.

**DO NOT** add an unguarded `drop_all` to any fixture. Under `TEST_DATABASE_URL` it deletes the
schema CI's migrations job just built and verified; against any other Postgres it is data loss.
This was caught twice in one PR, once in each file.

### 3.6 Cancellation is re-raised, absorbed only at the top level

`backend/app/workers/__main__.py` re-raises `CancelledError` after logging;
`asyncio.CancelledError` is suppressed alongside `KeyboardInterrupt` at the
`if __name__ == "__main__"` boundary. Awaiting a cancelled task and being cancelled yourself are
indistinguishable at that line, so swallowing it turns a real cancellation into a normal return.

`VERIFIED`: real `SIGTERM` → exit code `0`, `standalone job worker stopped` logged, zero
`CancelledError` in output.

### 3.7 The claim query is untouched

`.with_for_update(skip_locked=True)` in `backend/app/workers/jobs.py` was already multi-worker
safe. The spec says do not rewrite it. It has not been rewritten and must not be.

---

## 4. Test-infrastructure constraints — read before writing 1.5

1.5 will hit every one of these. They cost real debugging time in 1.3.

**SQLite silently drops `FOR UPDATE SKIP LOCKED`.** No error, no warning. A concurrency test on
SQLite exercises a query with no locking in it, passes, and proves nothing — worse than no test,
because the green tick gets cited as evidence. Postgres-only tests must `skipif` on a
non-Postgres `TEST_DATABASE_URL`.

**Postgres tests must use a module-scoped event loop.** `app.db.engine` is module-level and pools
connections; the per-test default loop leaves a connection bound to a loop the next test is not
in, failing with `attached to a different loop` **inside fixture setup**, where the traceback
points at asyncpg rather than at the cause. The working pattern is in
`backend/tests/test_worker_concurrency.py`:

- `pytest.mark.asyncio(loop_scope="module")` in `pytestmark`
- a module-scoped `autouse` `_db_schema` shadowing conftest's function-scoped one
- `pytest_asyncio.fixture(loop_scope="module")` on the schema fixture
- `asyncio_default_fixture_loop_scope = "function"` pinned in `backend/pyproject.toml`

**Dispose the engine after a deliberate mid-transaction cancellation.** A cancelled task abandons
an asyncpg connection mid-transaction; the pool does not know it is unusable and the next
checkout fails deep inside asyncpg. This is independent of loop scope.

**CI is the only place Postgres tests execute.** They run in the `migrations` job
(`.github/workflows/ci.yml`), which already stands up Postgres 16. That step fails if
`DATABASE_URL` is not Postgres **and** fails if pytest reports any skip — a green tick cannot
mean "never ran". Add 1.5's tests to that job the same way.

`VERIFIED`: the `Migrations up/down/up (Postgres)` job passes with the concurrency tests actually
executing.

---

## 5. Task 1.4 — Shared rate limiting on Redis (NEXT)

**Spec:** `docs/avora-new-state-august-16.md`, "1.4 — Shared rate limiting on Redis" (`AV-83`,
`E18`), plus threat review **F4** (`AV-97`).

**Current state** — `VERIFIED`:

- `backend/app/services/rate_limit.py:21` — `FixedWindowLimiter`, counters in
  `_hits: dict[str, tuple[float, int]]`
- `backend/app/services/rate_limit.py:71` — `login_limiter = FixedWindowLimiter(...)`, a
  module-global
- no `redis` dependency in `backend/pyproject.toml`
- `backend/tests/conftest.py` has an autouse `_reset_login_limiter` fixture clearing
  `login_limiter._hits`

**Requirements:**

- Move counters to Redis. **Redis is for rate-limit counters only** — Postgres remains the source
  of truth for all application state (`E18`). A second use of Redis gets its own decision.
- Throttle **per identifier, not per IP** (`SEC-14`). The API sits behind a proxy; one shared
  address means a global lockout. This is existing behaviour — preserve it.
- **F4 fallback:** on Redis failure, fall back to the in-process counter **and raise an alarm**.
  Never block logins wholesale (a self-inflicted outage an attacker triggers by degrading Redis)
  and never leave them uncounted (a free credential-stuffing window). Degrading from global to
  per-instance throttling is exactly today's behaviour.
- **The fallback path needs its own test and its own alert.** A silent fallback is the same as no
  fallback.
- Namespace keys by purpose and tenant so one caller cannot consume or collide with another's
  counter.

**Landmines specific to this codebase:**

- `BE-13`/`PERF-1`: no blocking calls. Use an async Redis client — the worker shares the API event
  loop.
- `BE-15`: read configuration through `get_settings()`, never `os.environ`.
- `AI-20`/`INF-9` precedent: a missing key degrades that surface with a clear message and never
  blocks startup. Apply the same shape to a missing or unreachable Redis.
- `QA-12`: ship the negative-case test.
- `_reset_login_limiter` in conftest must reset whichever store is active, or counts leak between
  tests.
- CI has no Redis service. Either add one to the workflow, or have the tests exercise the fallback
  plus a fake. Decide deliberately and record which, because "the test passed" must mean the Redis
  path actually ran — see the SQLite lesson in §4.

---

## 6. Task 1.5 — Two-instance correctness suite (AFTER 1.4)

**Spec:** `docs/avora-new-state-august-16.md`, "1.5 — Two-instance correctness suite" (`AV-84`).
A hard acceptance requirement. With API #1, API #2, Worker #1, Worker #2 running:

- Upload through API #1, retrieve and process through API #2.
- Failed logins spread across both APIs still trip one shared limit. *(needs 1.4)*
- One submission never produces two marking operations.
- One weekly send produces one email, even when a worker is killed mid-job.
- A worker killed halfway through a job recovers with no duplicate side effects.

**Known gap this suite must close:** nothing currently re-queues an orphaned `running` job row.
`backend/tests/test_worker_concurrency.py::test_a_job_left_running_by_a_killed_worker_is_visible`
records present behaviour rather than asserting a recovery that does not exist. 1.5 covers the
recovery case; 11.5 alerts on it.

Every constraint in §4 applies.

---

## 7. Environment and commands

From `backend/`:

```bash
.venv/bin/python -m pytest                 # 522 passed, 2 skipped (VERIFIED)
.venv/bin/ruff check .
.venv/bin/ruff format --check .            # this is what turned CI Lint red during 1.3
.venv/bin/python -m mypy app/services app/schemas
```

Postgres-only tests. No local Postgres or Docker was available during 1.3, so CI was their only
execution:

```bash
TEST_DATABASE_URL=postgresql+asyncpg://igcse:igcse@localhost:5432/igcse \
  .venv/bin/python -m pytest tests/test_worker_concurrency.py
```

Standalone worker: `python -m app.workers`. `VERIFIED` to claim and run a real job, report
`running` through the database, and stop cleanly on `SIGTERM`.

Live checks:

```bash
curl -s https://igcse-os-api.onrender.com/api/v1/health
curl -s https://igcse-os-api.onrender.com/api/v1/health/ready
```

---

## 8. Process constraints

- Nothing is committed directly to the default branch except documentation-only prose. **A code
  comment does not qualify** — it ships inside a code file.
- Every change under `backend/`, `frontend/`, `alembic/versions/` goes through a PR, however small.
- **The merge button belongs to the tutor/owner** unless they say otherwise for that change. For
  PR #54 they said "merge when ci green"; that authorization was for that PR only.
- Branches are disposable. A merged branch is finished — never reopen or stack on it. Start from
  the default branch.
- The default branch is still literally named `claude/igcse-os-planning-q8be0t`, pending rename.
- Do not switch branches, reset, rebase, or modify git history without asking the operator first.

---

## 9. Review-bot behaviour — affects how you work this repo

**Gitar commits directly to the PR branch**, it does not only comment. During 1.3 it pushed six
commits across three rounds. Consequences:

- `git push` will be rejected as non-fast-forward. Fetch and **merge** — do not rebase or force.
- Its fixes are sometimes better than yours and sometimes wrong. In 1.3 it correctly caught a reap
  bug and correctly fixed a residual, while separately shipping a health check that reported an
  unreadable table as healthy and a test teardown that dropped every table. Decide each overlap on
  merits and record the decision in the PR.
- It can leave the branch failing `ruff format --check`. Check formatting after every merge from it.

**A green check from a review bot does not mean it found nothing.** `cubic`, `CodeRabbit` and
`gitar-bot` all report a passing status check while leaving unresolved inline findings. Read them
explicitly:

```bash
env -u GITHUB_TOKEN gh api repos/OWNER/REPO/pulls/N/comments --paginate
```

**SonarCloud gates on new code** and failed PR #54 on a `C` reliability rating. Its findings are
fetchable without auth:

```bash
curl -s "https://sonarcloud.io/api/issues/search?componentKeys=muslim216_IGCSE-OS-product-repositiry-&pullRequest=N&resolved=false"
```

**`gh` needs the `env -u GITHUB_TOKEN` prefix** in this environment — an invalid `GITHUB_TOKEN`
environment variable overrides the valid keyring token.

---

## 10. Open items not owned by any Phase 1 task

- **11 failed jobs and one pending job ~9.7h old** on production as of 2026-08-28, per
  `/api/v1/health/ready`. The aged pending job is plausibly the scheduled narrative sweep and
  benign; the 11 failures are `UNVERIFIED` and predate Phase 1. Nothing watches the terminal
  `failed` state — `jobs.py` says so itself, and 11.5 is the task that fixes it.
- `RISK-5`: `analytics.py`, `reports.py` and `student_crm.py` still read v1 readiness tables
  directly while `/readiness/*` serves v2, so numbers can disagree. Untouched by Phase 1.
- `get_current_org_id` / `CurrentOrg` in `app/api/deps.py` remain unused. Organization scoping is
  applied per query against `user.organization_id`, which is what `SEC-7` requires. Do not cite the
  dependency as the mechanism.

---

## 11. RISK-1 chain status

`RISK-1`: the API is pinned to a single instance by three things at once.

| Link | Status | Closed by |
|---|---|---|
| Uploads on a persistent local disk | **RESOLVED (capability)** | 1.2 — `StorageBackend` + S3 backend; `storage_backend` still defaults to `local` |
| In-process worker | **RESOLVED (capability)** | 1.3 — `python -m app.workers`, DB-backed heartbeats; `run_worker_in_api` still defaults `True` |
| In-process rate limiter | **OPEN** | 1.4 |

All three are capability, not deployment. Scaling out remains a correctness change gated on 11.2
(`AV-85`).
