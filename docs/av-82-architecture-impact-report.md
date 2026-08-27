# AV-82 Task 1.1 — Architecture-Impact Report

**Status:** Complete · **Phase:** 1 (Scale foundation) · **Baseline:** `6826a35` (Phase 0 complete)

The sweep task 1.1 requires: every local-filesystem dependency, module-level mutable state,
process-local lock or counter, and single-process assumption in `backend/app/`, each classified
`SAFE_PROCESS_LOCAL` · `SHARED_STATE_REQUIRED` · `PERSISTENT_STORAGE_REQUIRED`.

Per §15 of the scalability brief, components needing no work are named as such rather than
padded into findings. **The headline: the sweep found no unknown blockers.** The three items
`RISK-1` already names are the three that exist. What the sweep adds is a hard ordering
constraint between 1.2 and 1.3, and a test-infrastructure gap that 1.5 depends on and the plan
does not list as a task.

## Method

Four greps across `app/` excluding `models/` and `schemas/` (declarative, no runtime state):
module-level mutable bindings; `asyncio`/`threading` synchronisation primitives, `lru_cache`
and `cached_property`; filesystem verbs (`open`, `Path`, `*_bytes`, `*_text`, `os.path`,
`mkdir`, `tempfile`, `shutil`, `FileResponse`); and `global` statements. Findings were then read
in context. Claims about SQLite versus Postgres behaviour were verified by compiling the actual
query against both dialects, not assumed.

## Findings

### PERSISTENT_STORAGE_REQUIRED

| Item | Location | Why it blocks a second instance |
|---|---|---|
| Local upload directory | `services/storage.py:94-166` | Files are written to the instance's own disk. A second instance serves 404 for everything the first one stored. |

**All filesystem access in the application is confined to `services/storage.py`.** The only
code outside it that touches a path is `services/assignments.py:43`, which calls `Path(name).stem`
on a *filename string* for a title — no I/O. This is the single most useful finding in the sweep:
the abstraction boundary task 1.2 needs already exists, and 1.2 is a re-implementation behind a
stable seam rather than a refactor that reaches across the codebase.

**29 call sites**, in three groups:

- **Writes (11)** — `save_upload` at `api/syllabus_uploads.py:44`, `api/past_papers.py:143,144,324`,
  `api/resources.py:81`, `api/submissions.py:151`, `api/classifieds.py:35,46`,
  `services/assignments.py:40,54`; `save_bytes` at `services/google_classroom.py:385`.
  One delete: `services/assignments.py:78`.
- **Worker reads (11)** — `read_file` feeding AI prompts: `services/marking.py:134,139,207,212,311`,
  `services/extraction.py:96,100,202,205`, `services/syllabus_extraction.py:62`.
  These become `download` on the new interface. **After 1.3 these run in a different process**,
  which is where the ordering constraint below comes from.
- **Serving (6)** — `absolute_path()` into `FileResponse`. These are what the F3 split governs.

### The F3 serving split, resolved per endpoint

Threat review F3 requires serving to split by sensitivity. Applying it to the six sites:

| Endpoint | Content | Ruling |
|---|---|---|
| `api/submissions.py:603` | Student submission files | **Proxy through the API.** `_tutor_owns()` runs on every view. |
| `api/classifieds.py:93` | Classified document | Signed URL |
| `api/classifieds.py:110` | Classified mark scheme | Signed URL |
| `api/past_papers.py:231` | Past-paper booklet | Signed URL |
| `api/past_papers.py:246` | Past-paper mark scheme | Signed URL |
| `api/resources.py:117` | Group resource | **Open — see Decisions.** |

Syllabus uploads have no serving endpoint; they are written once and read only by the worker.

### SHARED_STATE_REQUIRED

| Item | Location | Target | Task |
|---|---|---|---|
| `login_limiter` counters | `services/rate_limit.py:71` (the `_hits` dict inside the `FixedWindowLimiter` instance) | Redis | 1.4 |
| `_started_at` | `workers/jobs.py:62` | Database | 1.3 |
| `_last_loop_at` | `workers/jobs.py:63` | Database | 1.3 |
| `_job_started_at` | `workers/jobs.py:64` | Database | 1.3 |
| `_restart_times` | `workers/jobs.py:69` | Database | 1.3 |

The limiter's failure mode is specific and worth stating plainly: with N instances the effective
lockout threshold becomes 10 × N. At two instances an attacker gets 20 password attempts per
identifier per window instead of 10. The counter is not merely inaccurate — the control weakens
in direct proportion to the thing Phase 1 exists to enable.

The four worker variables are read by `/api/v1/health/ready`. Once the worker is a separate
process (1.3) the API cannot see them at all, and the readiness endpoint would report the health
of a worker that is not running in that process. `jobs.py:57-60` already carries a comment
predicting exactly this and instructing the move; that comment is the design note for 1.3 and
should be updated rather than deleted (`CODE-13`).

### SAFE_PROCESS_LOCAL

Each of these is module-level mutable state that is nonetheless correct under N instances,
because it is derived identically in every process and never mutated by request handling.

| Item | Location | Why it is safe |
|---|---|---|
| `_handlers` | `workers/jobs.py:55` | Populated at import by the `@handler` decorator. Identical in every process; never written at runtime. |
| `MODEL_PRICING` / `model_pricing()` | `services/ai.py:419,422` | Empty literal merged with the `AI_MODEL_PRICING` env var. Same env, same result. Cache is per-process and immutable. |
| `get_settings()` | `config.py:121` | Environment-derived, immutable for the process lifetime. |
| `_dummy_hash()` | `api/auth.py:107` | Deliberately a random value per process. Its purpose is to make a login miss cost the same as a wrong password; bcrypt's cost depends on the work factor, not the hash value, so per-instance variance changes nothing. |
| `log` | `main.py:61` | Logger handle. |
| Module constants | `main.py:92,160,167,172`; `workers/jobs.py` thresholds; `services/rate_limit.py:68-69`; `services/storage.py` MIME and size tables | Immutable. |

### Single-process assumptions

| Assumption | Location | Task |
|---|---|---|
| Worker runs as an asyncio task inside the API's `lifespan` | `main.py:139` (`asyncio.create_task(_supervised_worker())`) | 1.3 |
| HEIC transcode runs on the event loop | `services/storage.py:42` (`_to_jpeg`) | 1.2 |

`_to_jpeg` is not a multi-instance blocker — it is a `BE-13`/`PERF-1` violation that 1.2 is
required to fix while it is in the file. Every iPhone photo upload currently blocks request
serving for every other user of that instance for the duration of the decode.

## NO CHANGE REQUIRED

Named explicitly so later phases do not re-audit them:

- **The job claim.** `workers/jobs.py:184` uses `.with_for_update(skip_locked=True)`. Two workers
  cannot claim the same job. This is already correct for N workers and the plan says not to
  rewrite it. It does need the race *test* (1.5).
- **Authentication.** JWTs are stateless and `token_version` lives in the database, so revocation
  already works across instances.
- **OAuth `state`.** `security.create_state_token` / `verify_state_token` — a signed token, not a
  server-side session. No shared store needed.
- **Synchronisation primitives.** There are none. No `asyncio.Lock`, `threading.Lock`,
  `Semaphore`, `Event` or in-process `Queue` anywhere in `app/`.
- **Session and cache stores.** None exist. There is no in-memory cache of application data.
- **The job queue itself.** Postgres-backed by `ADR-0002`; correct across processes by design.

## Two consequences the task list does not currently carry

### 1. 1.2 must land before 1.3 can deploy separately

The plan lists 1.2, 1.3 and 1.4 as independent, all gated only on 1.1. For 1.4 that holds. For
1.2 and 1.3 it does not, because of the eleven worker-side `read_file` calls above.

A worker split into its own process (1.3) but still reading `UPLOAD_DIR` from local disk (pre-1.2)
can only work if it happens to run on the same machine with the same disk mounted. On Render that
means the worker cannot be a separate service — which is the entire point of 1.3. **1.3's code can
be written in parallel, but its deployment depends on 1.2 being live.** Sequencing 1.2 first
avoids a half-migrated state where the worker silently cannot read the files it is asked to mark.

Per F7, the worker also needs **its own storage credentials** once it is a separate service.

### 2. 1.5 needs a real Postgres test harness, which does not exist yet

Verified rather than assumed — the claim query compiled against both dialects:

```
SQLite  : SELECT ... FROM jobs LIMIT ? OFFSET ?
Postgres: SELECT ... FROM jobs LIMIT %(param_1)s FOR UPDATE SKIP LOCKED
```

**SQLite silently drops `FOR UPDATE SKIP LOCKED`.** Not an error, not a warning — the clause
vanishes. The test suite forces `sqlite+aiosqlite:///:memory:` in `conftest.py` before any app
import (`RISK-3`), so a multi-worker race test written against the current harness would exercise
a query with no locking in it, pass, and prove nothing. It would be worse than no test, because
it would be cited as evidence.

1.5 therefore needs a Postgres-backed test path — at minimum for the concurrency tests, which also
need genuinely concurrent sessions rather than the suite's single `StaticPool` connection. CI
already stands up Postgres 16 for the `migrations` job, so the infrastructure exists to borrow.
**This is unestimated work that 1.5 depends on and should be scoped into it.**

## Decisions still open

1. **Object storage target.** The interface is vendor-neutral by requirement, but the harness in
   1.5 and the credentials in 1.2 need a concrete target. Recommendation: build against the S3
   API, run MinIO in CI, point production at Cloudflare R2 — submission files are proxied through
   the API on every view under F3, so per-view egress is a recurring cost and R2 does not charge it.
2. **Group resources — proxy or signed URL?** `api/resources.py:117` is the one serving site F3
   does not name. They are tutor-authored and carry no personal data, which argues for a signed
   URL; they are also student-visible, which is the population F3 is protective about.
   Recommendation: signed URL, on the grounds that the sensitivity test in F3 is *whose personal
   data is in the file*, and the answer here is nobody's.
3. **Redis provider.** Render offers a managed Redis in-region. No reason found to look further.

## Rule and document impact

- `RISK-1` and §08's constraint chain are the target of this phase and get updated as each link
  is unwound, not before.
- `INF-5` (single origin) stays Active — Phase 1 does not deploy anything.
- `FE-1` is amended by 1.2: `fetchFileUrl()` remains the sanctioned bypass for proxied
  submissions, and signed-URL fetches become a second, distinct path that must be described
  rather than left implicit.
- `jobs.py:57-60` and the `services/rate_limit.py` module docstring both predict their own
  replacement. Update both in the PR that performs it (`CODE-13`).
