# ADR-0002 — Postgres-backed job queue instead of a broker

**Status:** Accepted · **Date:** 2026-08 (retroactive) · **Owner:** Architecture owner
**Supersedes:** — · **Superseded by:** —

## Context

Every AI operation in MANARA is too slow for a request cycle: question extraction from a PDF
booklet, marking a submission, synthesizing a readiness score, generating a report,
importing from Google Classroom. All of it must run asynchronously, survive a restart, and
be observable when it fails.

The conventional answer is Celery or RQ with Redis, or a hosted queue.

## Decision

Jobs are **rows in a Postgres table** (`jobs`, defined in `backend/app/models/homework.py`),
claimed by an **in-process asyncio worker** started in `main.py`'s `lifespan`.

- Handlers are registered by type string in `main.py`; there are eight.
- The worker claims the oldest eligible pending job with
  `.with_for_update(skip_locked=True)`, so multiple workers would be safe without changes.
- `MAX_ATTEMPTS = 2` — one retry.
- `POLL_SECONDS = 2.0`.
- `Job.run_after` (nullable) holds a job until a future time, filtered in the claim query.
  This is the primitive `enqueue_readiness_v2_debounced()` is built on.
- Failures persist to `Job.error`, and domain-specific errors also persist to columns like
  `Assignment.extraction_error` and `Submission.ai_error`.

## Alternatives considered

**Celery + Redis.** Mature, with retries, scheduling, and monitoring built in. It would cost
a second datastore to run, back up, and reason about; a second failure mode; and a second
place a job can be lost. Its retry and scheduling features are a few dozen lines here.

**RQ.** Simpler than Celery, same Redis dependency.

**A hosted queue (SQS or similar).** Adds a network dependency and vendor coupling for a
workload measured in tens of jobs per day.

**Fire-and-forget `asyncio.create_task`.** Free, and loses every in-flight job on restart —
including a marking run a student is waiting for.

## Consequences

**Easier:** a job is a row you can `SELECT`. Diagnosing a stuck pipeline is a query, not a
Redis inspection. Jobs survive restarts because they were never in memory. Tests drive jobs
synchronously with `process_one_job()` and need no broker. One datastore means one backup
and one restore.

**Harder:** polling costs a query every two seconds and adds up to two seconds of latency to
every job. There is no built-in dashboard, no dead-letter queue, and no scheduled/recurring
job support beyond `run_after`. At-least-once delivery makes **handler idempotency a
correctness requirement**, not a nicety — which is why it is a Critical rule in §04.

**Bad consequence, explicitly:** because the worker lives in the API process, it dies with
the API. That is RISK-4, and it is a direct cost of this decision.

> **Update — the "invisible" half of that consequence has been addressed.** As originally
> written this paragraph continued "and its death is invisible — the health endpoint keeps
> returning `ok`", which was true and is no longer. `_supervised_worker()` restarts the loop
> if it raises or returns, and `GET /api/v1/health/ready` reports worker state, queue depth
> and the oldest pending job, returning 503 when the worker is unhealthy. **The decision
> itself is unchanged and so is its structural cost:** the worker still shares the API's
> process and event loop, so a process death still stops all background work, and scaling to
> a second instance is still a correctness change (`RISK-1`). What is different is that the
> failure can now be seen by anyone who asks. Nothing yet asks — see §11.

## Revisit when

Job volume makes two-second polling or single-process throughput the bottleneck; or the API
scales beyond one instance, at which point the worker should move to its own service first
(ADR-0001). The `SKIP LOCKED` claim already supports that move.
