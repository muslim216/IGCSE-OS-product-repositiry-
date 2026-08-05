# 10. Performance Engineering

> **Volume 3 — Platform Engineering** · Engineering Constitution v1.2 · Status: Active
> **Owner:** Founder (see `governance/ownership.md`)
>
> Governs latency, throughput, and cost — which in this system are the same discipline.

## Contents

- [Purpose](#purpose)
- [Scope](#scope)
- [Sources](#sources)
- [Principles](#principles)
- [Current Reality](#current-reality)
  - [The shape of the system](#the-shape-of-the-system)
  - [Where time actually goes](#where-time-actually-goes)
  - [Database performance](#database-performance)
  - [Cost as a performance dimension](#cost-as-a-performance-dimension)
  - [Frontend](#frontend)
  - [What is measured today](#what-is-measured-today)
- [Standards](#standards)
- [Known Gaps](#known-gaps)
- [Review Triggers](#review-triggers)

---

## Purpose

Answers *what "fast enough" means here, and what will stop being fast first*. MANARA's
performance profile is unusual in two ways worth stating before any rule: the API and its
background worker share one process and one event loop, so a slow job degrades request
serving; and the dominant scaling cost is not CPU but per-call AI spend, which makes
coalescing a performance technique measured in currency.

## Scope

**In scope:** latency and throughput budgets; async discipline; database query performance and
its relationship to §06's indexing contract; caching; AI cost and latency; frontend bundle and
render behaviour; how to profile each layer.

**Out of scope:** the indexing rules themselves (§06); AI routing (§09); the single-instance
constraint and how to unwind it (§08); alerting on any of this (§11).

### Non-goals

- **No premature optimization.** Write the clear version, measure, then optimize what is
  actually slow — and leave a comment saying what you measured.
- **No caching layer.** No Redis, no memcached, no application-level result cache. Postgres is
  the datastore; the browser holds a query cache.
- **No CDN for API responses.** Every response is authenticated and per-user.
- **No horizontal scaling today.** Three constraints prevent it (§08). Performance work
  currently means making one instance sufficient.
- **No performance budget enforcement in CI.** CI exists now and runs both suites, the type
  check and the migration cycle — but nothing in it measures latency, query counts, or bundle
  size, so every budget in this document is still checked by a human or not at all.

## Sources

Written from: `backend/app/main.py`; `backend/app/workers/jobs.py`;
`backend/app/services/readiness_v2_ai.py`; `backend/app/services/ai.py`;
`backend/app/services/marking.py`; `backend/app/db.py`; `backend/app/config.py`;
`backend/app/models/`; `alembic/versions/`; `frontend/src/main.tsx`;
`frontend/vite.config.ts`; `render.yaml`.

---

## Principles

**P1 — One process serves everything.** The API and the job worker share an event loop. A
blocking call anywhere stalls every user, not just the caller.

**P2 — Cost is a performance dimension.** An expensive model call is a performance problem
whose unit is dollars. The techniques are the same: batch, coalesce, cache, skip.

**P3 — Measure before optimizing, and record what you measured.** A comment naming the
measurement is worth more than the optimization it justifies.

**P4 — Cheap-now-expensive-later is not premature.** An index on a column you know will be
filtered, an eager load on a relationship you know will be traversed, and a coalesced job are
design, not optimization.

**P5 — Slow is a correctness problem when it is unbounded.** An endpoint returning every row
is not slow, it is broken at a size nobody has reached yet.

---

## Current Reality

### The shape of the system

One Render `starter` instance runs uvicorn **and** the asyncio job worker, against one
`basic-256mb` Postgres. Vercel serves static assets from its edge.

The worker is started in `main.py`'s `lifespan` as an `asyncio` task. It polls every 2 seconds
when idle and, when a job is claimed, **runs the handler on the same event loop that serves
requests**. A handler that blocks — a synchronous HTTP call, an unawaited CPU-bound loop, a
sync database driver — stops request serving for its duration.

This is the single most important performance fact about the system, and it is a direct
consequence of `ADR-0002` and the single-instance constraint in §08.

### Where time actually goes

| Path | Dominant cost | Typical shape |
|---|---|---|
| Ordinary CRUD request | Postgres round-trips | Milliseconds; unindexed scans are the risk |
| List endpoint | Full result set, unpaginated | Grows monotonically with data (§05) |
| File download | Disk read plus transfer | Bounded by the 20 MB upload cap |
| Question extraction | One AI call over a PDF | Seconds to minutes; asynchronous |
| Marking a submission | One AI call over page images | Seconds to minutes; asynchronous |
| Readiness synthesis | One frontier-model call | Seconds; asynchronous and **debounced** |
| Report generation | One frontier-model call | Seconds; asynchronous |
| Chat | Streaming tokens | First token is what the user perceives |

Every AI path is a job, not a request. The user-visible latency for those is **queue wait plus
model time**, and queue wait is where the single worker shows: jobs are strictly serial. Two
students submitting at once means the second waits for the first's marking call to complete.

### Database performance

Three facts from §06 that are performance facts before they are design ones:

1. **Foreign key columns are not indexed.** Postgres does not index them automatically, so
   every join and every `WHERE parent_id = ?` on a growing table is a sequential scan.
2. **The models declare one index; the migrations create five.** The four that exist only in
   migrations are absent from the SQLite test schema, so **no test ever exercises an indexed
   query plan**.
3. **No endpoint is paginated.** All 29 list endpoints return the complete result set.

The tables that will hurt first, in order, are the append-only ones:
`factor_evaluations` (one row per factor per run, on the most frequent background job),
`evidence`, `ai_usage_events`, and `chat_messages`. `factor_evaluations` has no retention
policy implemented (`DB-20` is Draft).

`db.py` uses SQLAlchemy's default pool settings — nothing is tuned, which is appropriate at one
instance against a small database and is a thing to revisit at the same moment as everything
else in §08's constraint chain.

### Cost as a performance dimension

Three mechanisms already exist and are the patterns to copy:

**Debounced synthesis.** `enqueue_readiness_v2_debounced()` no-ops if a run for that
(student, subject) is already pending, and otherwise schedules one
`READINESS_V2_COALESCE_SECONDS` (default 600) out. Auto-marking can finalize a burst of
submissions in seconds; without this, each one would trigger a separate frontier-model
synthesis. **This turns O(submissions) frontier calls into O(1) per ten-minute window.**

**Skipping the call entirely.** `mark_submission` skips the AI call when every question is
already decided — so a re-run after a tutor finishes reviewing costs nothing.

**Prompt caching.** `file_block(..., cache=True)` sets Anthropic's ephemeral cache control,
used to reuse a shared mark scheme across a batch. It is a no-op on Gemini, which caches
implicitly.

Against that: **nothing bounds spend.** No per-organization budget, no cap, no circuit breaker,
and `AI_MODEL_PRICING` is empty by default so the reported figure is `unpriced_call_count`
rather than a number (`RISK-12`).

### Frontend

`main.tsx` constructs a **bare `new QueryClient()` with no default options** — no `staleTime`,
no `retry` policy, no `refetchOnWindowFocus` override. The practical effect is refetch-heavy
behaviour: every mount of a component with a query hits the network unless a fetch is already
in flight.

Polling is generally well-behaved: three pages use the **function form** of `refetchInterval`,
inspecting the last result and stopping themselves once the async work has settled. One fixed
interval exists — `ActivityMenu.tsx` at 120 seconds.

`npm run build` is `tsc -b && vite build` with default Vite chunking. There is no bundle
analysis, no route-level code splitting, and no size budget. The application is a single bundle
for an authenticated tool behind a login, so first-load cost is paid once per session rather
than per visitor — but it is paid on a student's phone.

Vercel serves assets from its edge; every `/api/*` call is proxied server-side to Render, which
adds a hop.

### What is measured today

**Nothing.** No timing middleware, no metrics endpoint, no APM, no slow-query log, no bundle
report, no load test. The only performance-adjacent data in the system is
`ai_usage_events`, which records tokens per call — a cost signal, not a latency one.

Every budget in the Standards section below is therefore a **target to start measuring
against**, not a measured baseline. That distinction is deliberate and is why they are
`SHOULD`.

---

## Standards

### Async discipline

**`PERF-1` — MUST NOT · Critical · Active**
Never make a blocking call in a request handler, service, or job handler. Use async clients for
I/O; move genuinely CPU-bound work to a thread.
*Rationale:* P1 — the worker shares the API's event loop, so one blocking call stalls request
serving for every user. Same rule as `BE-13`, stated here because this is where its cost is
explained.

**`PERF-2` — MUST · Important · Active**
Long-running work is a job, not a request. Return `202` with a pollable resource.
*Rationale:* every AI path already does this; a synchronous AI call would hold a connection for
minutes and block the loop.

**`PERF-3` — SHOULD · Important · Active**
A job handler that will take more than a few seconds does its slow work in as few awaited calls
as possible, because jobs are strictly serial on one worker.
*Rationale:* queue wait is the user-visible latency for every AI surface; a handler that makes
five sequential model calls delays every other student's work by the sum.

### Database

**`PERF-4` — MUST · Important · Active**
Every foreign key that is filtered or joined has an index, declared in the model **and**
created in the migration.
*Rationale:* `DB-11` and `DB-12`. Unindexed foreign keys are the most likely first performance
failure, and the model/migration divergence means tests would not reveal it.

**`PERF-5` — MUST NOT · Important · Active**
Never query inside a loop over rows. Use `selectinload`/`joinedload` for relationships you will
traverse, or fetch in one statement keyed by id.
*Rationale:* N+1 is the classic ORM failure and it scales with data rather than with code.

**`PERF-6` — MUST · Important · Active**
An endpoint returning a collection that can grow without bound is paginated from its first
version.
*Rationale:* `API-12`. P5 — unbounded is broken, not slow.

**`PERF-7` — SHOULD · Important · Active**
Aggregate in the database rather than in Python. Count with `COUNT`, not `len(rows)`.
*Rationale:* fetching rows to count them transfers and materializes data the answer does not
need.

**`PERF-8` — SHOULD · Important · Active**
Before merging a query over a table expected to exceed ~10,000 rows, check its plan with
`EXPLAIN ANALYZE` against Postgres and note the result in the pull request.
*Rationale:* P3, and SQLite tests cannot reveal a Postgres plan.

### AI cost and latency

**`PERF-9` — MUST · Important · Active**
Work that can burst is coalesced or skipped rather than called per item.
*Rationale:* `AI-18`. `enqueue_readiness_v2_debounced()` and `mark_submission`'s skip are the
two existing patterns; both convert per-item spend into per-window spend.

**`PERF-10` — SHOULD · Important · Active**
Reuse a shared document across a batch with `cache=True` where supported.
*Rationale:* a mark scheme re-sent per submission is the largest avoidable token cost in the
product.

**`PERF-11` — MUST NOT · Important · Active**
Never call a model inside a loop over student work without an explicit, stated bound on the
iteration count.
*Rationale:* the cost is unbounded and the worker is serial, so it is simultaneously the most
expensive and the most blocking thing the system can do.

**`PERF-12` — SHOULD · Recommended · Active**
Route a surface to the cheapest model that meets its quality bar, and record why in the
surface's row in §09.
*Rationale:* the existing split — bulk document work on the cheaper provider, synthesis on the
capable one — is this rule already applied.

### Frontend

**`PERF-13` — SHOULD · Recommended · Active**
Set a `staleTime` on queries whose data does not change per interaction.
*Rationale:* the `QueryClient` has no defaults, so every mount refetches; readiness and syllabus
data in particular change on a timescale of hours.

**`PERF-14` — MUST · Important · Active**
Poll with the function form of `refetchInterval`, returning `false` once the work has settled.
*Rationale:* `FE-9`. A fixed interval polls forever and costs a request per tick after the
answer arrived.

**`PERF-15` — SHOULD · Recommended · Active**
Keep list rendering proportional to what is visible. A list that can exceed a few hundred rows
is paginated or virtualized.
*Rationale:* pairs with `PERF-6` — an unpaginated endpoint and an unvirtualized list fail
together.

### Budgets

**`PERF-16` — SHOULD · Recommended · Active**
Work to the targets in the table below. They are targets to measure against, **not measured
baselines**.
*Rationale:* P3 — a target that nothing measures is a hypothesis, and these are stated so the
first real measurement has something to disagree with.

| Path | Target |
|---|---|
| Read endpoint, p95 | < 300 ms server time |
| Write endpoint, p95 | < 500 ms server time |
| Job queue wait, p95 | < 30 s |
| Marking a submission, end to end | < 3 min |
| Readiness synthesis after the debounce window | < 60 s |
| Chat first token | < 2 s |
| Frontend first contentful paint, 4G mobile | < 2.5 s |
| Initial JavaScript bundle | < 400 KB gzipped |

**`PERF-17` — SHOULD · Important · Active**
A change expected to affect one of these paths states its expected effect in the pull request,
and measures it if the effect is more than incidental.
*Rationale:* nothing measures performance automatically — CI gates correctness, not latency —
so the review is the only checkpoint for every budget above.

---

## Known Gaps

| Gap | Why it matters | Severity |
|---|---|---|
| **Nothing is measured.** No timing middleware, no metrics, no APM, no slow-query log, no bundle report, no load test. | Every budget above is a target with no baseline, and a regression is invisible until a user reports it. See §11. | `blocking` |
| **Foreign keys are unindexed** and four of five indexes are invisible to the models and to tests. | The most likely first performance failure, in the place tests cannot detect it. `DB-11`, `DB-12`. | `before scale` |
| **No pagination on 29 list endpoints.** | The append-only tables grow monotonically; the first to exceed a request timeout does so in production. `API-12`. | `before scale` |
| **Jobs are strictly serial on one worker.** | Queue wait is the user-visible latency for every AI surface, and two concurrent submissions serialize. Unwinding is step 2 of §08's constraint chain. | `before scale` |
| **`QueryClient` has no defaults** — no `staleTime`, no retry policy. | Refetch-heavy behaviour on every mount, and inconsistent retry semantics across the app. | `nice to have` |
| **No bundle analysis, code splitting, or size budget.** | `PERF-16`'s bundle target is unverified. Students load this on phones. | `nice to have` |
| **No per-call AI timeout.** Job-level retry is the only recovery, and it has no backoff. | A hung provider call occupies the single worker until the SDK's own default fires. §09, §04. | `before scale` |
| **No spend bound of any kind**, and `AI_MODEL_PRICING` is empty so spend is not even reported as a number. | `PERF-9` through `PERF-12` are the only cost controls, and all are conventions. `RISK-12`. | `before scale` |
| **`factor_evaluations` has no implemented retention policy.** | The highest-growth table in the schema, on the most frequent background job. `DB-20` is Draft. | `before scale` |

---

## Review Triggers

Update this document when:

- Any measurement is introduced — the budgets stop being hypotheses and become baselines.
- The worker moves out of the API process, which retires `PERF-1`'s primary rationale and
  changes the serial-queue analysis.
- Pagination, indexing, or the retention policy lands.
- A caching layer is introduced.
- The `QueryClient` gains defaults, or code splitting is added.
- AI budgets, timeouts, or a circuit breaker are introduced.
- The instance count or database plan changes.
