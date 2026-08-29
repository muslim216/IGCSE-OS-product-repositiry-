# Phase 1 (AV-82, Scale foundation) — agent handoff

**Audience: agents, not humans.** Dense and declarative on purpose. Assertions here are either
(a) verified in-session and marked `VERIFIED`, or (b) sourced to a file path or rule ID. Anything
unverified is marked `UNVERIFIED`. Do not upgrade an `UNVERIFIED` claim without testing it.

| Field | Value |
|---|---|
| Phase | 1 — Scale foundation (`AV-82`) |
| Spec of record | `docs/avora-new-state-august-16.md` §"Phase 1 — Scale foundation" (~lines 937–1045) |
| State as of | branch `feat/av-83-1.4-redis-rate-limiting`, off commit `67c9b0c` |
| Handoff written | 2026-08-28 · updated 2026-08-29 (task 1.4) |
| Migration head | `0027_worker_heartbeats` |
| Tasks done | 1.1, 1.2, 1.3, **1.4 (in review)** |
| Tasks remaining | **1.5** (last; unblocked once 1.4 merges) |

---

## 1. Task status

| ID | Task | Status | PR | Landed in |
|---|---|---|---|---|
| 1.1 | Architecture-impact report | **DONE** | #52 | `docs/av-82-architecture-impact-report.md` |
| 1.2 | Object storage | **DONE** | #53 | `app/services/storage.py`, `app/api/file_responses.py` |
| 1.3 | Worker as a separate process | **DONE** | #54 | `app/workers/*`, `app/models/workers.py`, migration `0027` |
| 1.4 | Shared rate limiting on Redis | **IN REVIEW** | — | `app/services/rate_limit.py`, `tests/test_rate_limit.py`, CI `redis:7-alpine` service |
| 1.5 | Two-instance correctness suite | **NOT STARTED** | — | unblocked once 1.4 merges |

1.5 requires 1.2–1.4 complete. 1.4 is in review, so 1.5 is the only remaining Phase 1 task
and starts when 1.4 merges.

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
| Worker | in-process | `run_worker_in_api` defaults `True` (`backend/app/config.py`) |
| Storage backend | `local` | `storage_backend` defaults `"local"` (`backend/app/config.py`) |
| Rate-limit store | in-process *(operator-managed)* | `redis_url` defaults `None`, and `render.yaml` declares `REDIS_URL` as `sync: false` — dashboard-managed, so the file does **not** prove the deployed value. Confirm with `rate_limit.limiters[].configured` on `/health/ready` before relying on it. |
| Liveness | `200` | `GET /api/v1/health` |
| Readiness | `status: ok`, worker `running` | `GET /api/v1/health/ready` |
| Migration `0027` | applied | readiness reads `worker_heartbeats` and answers |

**DO NOT**, as part of 1.5: deploy a second instance, add a worker service to `render.yaml`,
set `RUN_WORKER_IN_API=false`, or set `REDIS_URL` on the deployed service. That is Phase 11 work
and 11.2 gates it.

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

## 5. Task 1.4 — Shared rate limiting on Redis (BUILT, in review)

**Spec:** `docs/avora-new-state-august-16.md`, "1.4 — Shared rate limiting on Redis" (`AV-83`,
`E18`), plus threat review **F4** (`AV-97`). Rules added: `SEC-29`, `SEC-30` (§07).

### What was built

`backend/app/services/rate_limit.py` now holds three things instead of one:

- `FixedWindowLimiter` — **unchanged**, and still the process-local store. It is the fallback,
  not dead code.
- `RedisWindowStore` — the same fixed window with the window start baked into the key and a TTL
  on every key, so rollover and cleanup are Redis's job. `record()` is `INCR` + `EXPIRE` in one
  `MULTI/EXEC`; `EXPIRE` fires unconditionally because a first-hit-only `EXPIRE` that loses its
  race leaks a key that would then throttle an identifier forever.
- `RateLimiter` — the facade `api/auth.py` calls. Async (`BE-13`/`PERF-1`), picks the store per
  call, falls back, and owns the breaker and the alarm.

`login_limiter` is now a `RateLimiter`; `api/auth.py`'s three call sites are `await`ed.
`ALL_LIMITERS` + `rate_limit_health()` feed a new `rate_limit` block in `/api/v1/health/ready`.

### Decisions a later agent should not re-litigate

**Wall clock in Redis, monotonic in process.** `RedisWindowStore` buckets on `time.time()`.
`time.monotonic()` has a per-process epoch, so two instances would bucket the same instant into
different windows and each enforce its own — the exact defect the shared store exists to remove.
The in-process fallback keeps `monotonic` because it is per-process by definition.

**The identifier is hashed into the key** (`SEC-30`). A Redis keyspace is enumerable by anything
holding the connection string; a store explicitly *not* the source of truth must not become a
roster of who has an account.

**Login's tenant is `global`.** The lookup in `api/auth.py` matches an email or username across
every organization, so there is no tenant to scope to until *after* the credential is accepted.
Scoping it earlier would let an attacker mint a fresh allowance by guessing a tenant. The
`tenant=` parameter exists for the limiters `RISK-12` will want.

**`record()` writes both stores, always, and `is_limited()` ORs them.** A failure landing just
before an outage must be visible to the store that takes over. Reading only the Redis answer
would hand an attacker a fresh allowance the moment Redis recovers, because failures counted
during the outage are **never backfilled** — Redis would start that identifier at zero while the
local counter already held ten. Covered by
`test_a_recovered_redis_does_not_hand_back_a_fresh_allowance`.

**The dual-write contract, stated plainly.** Failures counted while the breaker is open never
reach Redis. The instance that saw them keeps enforcing them; the other instances never learn
about them. Throttling during an outage is therefore per-instance — which *is* the degradation
F4 accepts, not a separate gap. Backfilling was rejected: it means queueing writes against a
store already known to be failing, then replaying them into a window that has since rolled over.
Note also that the two stores bucket on different clocks (`monotonic` locally, `time.time()` in
Redis), so an identifier can stay limited into the start of the next Redis window — conservative,
and cleared by any successful login.

**There is a circuit breaker** (3 consecutive failures → skip Redis for 30s). Without it every
login during an outage pays the socket timeout twice before falling back, which turns a degraded
dependency into a slow authentication endpoint for the whole outage — a smaller version of the
outage F4 forbids. `record_success()` closes it, and there is a test that a recovered Redis is
used again: the breaker is a pause, not a one-way door.

**`/health/ready` answers 503 when a *configured* Redis is unreachable, and stays healthy when
Redis is not configured at all.** No Redis is the documented single-instance mode. A configured
Redis that stopped answering has silently multiplied the effective login allowance by the
instance count, which has no other symptom — that is the alert F4 asks for. `/api/v1/health`
(liveness, what Render's `healthCheckPath` polls) is untouched, so this cannot cause a restart
loop.

**Timeouts are bounded twice** — `socket_timeout`/`socket_connect_timeout` on the client and
`asyncio.wait_for` on every call. `REDIS_TIMEOUT_SECONDS` defaults to `0.25` and a startup
validator rejects anything outside `(0, 5]`: zero would make every call time out instantly and
look exactly like a permanent outage, degrading to per-instance counting on a config typo.

### CI decision — recorded deliberately, per §4

**A real `redis:7-alpine` service was added to the `backend` job**, not a fake. The alternative
was rejected for the reason SQLite was rejected in 1.3: a fake that never runs the real client
passes while exercising nothing, and the green tick then gets cited as evidence.

- `TEST_REDIS_URL` is set as job env — deliberately **not** `REDIS_URL`, which would put the
  whole suite on Redis and make every test's login throttling depend on a service most of them
  have no opinion about. `tests/test_rate_limit.py` points the limiter at it per test.
- A guard step re-runs `tests/test_rate_limit.py -v -ra` and **fails on any skip**, the same
  guard the multi-worker tests have in the `migrations` job.
- `docker compose --profile full up -d redis` runs one locally. There was no Docker or local
  Redis in the session that built this, so — exactly as with Postgres in 1.3 — **CI is the only
  place the Redis path has executed. The three Redis tests are `UNVERIFIED` locally.**

### Test-infrastructure notes

`tests/conftest.py`'s `_reset_login_limiter` is now **async** and resets whichever store is
active: the local dict, the `_Degradation` breaker state, and — when a limiter has a Redis store
— its keys by namespace prefix via `SCAN`, never `FLUSHDB`. Async so the flush runs on the
test's own loop rather than one the fixture invented, the same reasoning as `_db_schema`.

The `broken_redis` fixture monkeypatches `RedisWindowStore.client`, so the fallback tests run
everywhere with no service. Teardown order is what makes this safe: `monkeypatch` is set up
after the autouse fixture and therefore torn down before it, so `redis_url` is already reverted
by the time the reset fixture asks whether a Redis store exists.

## 6. Task 1.5 — Two-instance correctness suite (NEXT)

**Spec:** `docs/avora-new-state-august-16.md`, "1.5 — Two-instance correctness suite" (`AV-84`).
A hard acceptance requirement. With API #1, API #2, Worker #1, Worker #2 running:

- Upload through API #1, retrieve and process through API #2.
- Failed logins spread across both APIs still trip one shared limit. *(1.4 built this;
  `test_two_instances_share_one_limit` is the two-object version, 1.5 wants two real processes)*
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
| In-process rate limiter | **RESOLVED (capability)** | 1.4 — `RateLimiter` on Redis with an alarming fallback; `redis_url` still defaults unset |

All three are capability, not deployment: `STORAGE_BACKEND=local`, `RUN_WORKER_IN_API=true`,
`REDIS_URL` unset. Scaling out remains a correctness change gated on 11.2 (`AV-85`).
