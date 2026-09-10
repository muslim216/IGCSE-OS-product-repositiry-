# Implementation Plan: Backend Remediation (Forensic Audit Follow-up)

> **STANDING RULE — READ FIRST: NO PRODUCT OR ARCHITECTURE CHANGE WITHOUT THE OWNER'S EXPLICIT APPROVAL.**
> Tasks tagged **[GATED]** are proposals only — no branch, no code, no migration, no config change until
> the owner explicitly approves that task's scope and design. No agent approval counts. See "Standing rule" below.

## Overview

Execute the remediation roadmap from `avora-backend-forensic-audit-REPORT.md` (sections B–J) in dependency order: measure first, then kill the P0s (serial-worker head-of-line blocking, unbounded AI calls inside open transactions), then remove the O(N) query paths and missing indexes, then paginate and add retention, and only then scale the worker/storage/pool layers. Every task ships as its own short-lived branch + PR into the default branch (repo rule: nothing commits to main directly; owner merges). No code is written by this plan — it is the build order.

## Standing rule

**No product or architecture change ships without the owner's explicit approval.** In this plan that means: T1.4, T1.5, T2.1, T2.6, T3.1, T3.2, T3.3, T3.4, T3.5, T3.7, T4.1, T4.2 are **proposals** — each needs a "proceed" from the owner (scope + design agreed) before any branch is cut. Purely internal fixes (timeouts, session split, indexes, batched queries, streaming, KB cap) still get a PR review as normal, but nothing product-visible or structural merges on agent say-so.

## Architecture Decisions

- **Worker lanes, not just more workers (P0-1):** separate marking/extraction (slow, large) from readiness/report/narrative (fast) lanes with per-lane concurrency, rather than raising global parallelism. Rationale: a second generic worker still lets a marking burst starve fast jobs; lanes bound the blast radius. Claim query already uses `FOR UPDATE SKIP LOCKED`, so parallel claimants are safe.
- **Timeouts + session split together (P0-2):** bounding the AI call without splitting the session still pins a connection for the full timeout; splitting without a timeout still hangs forever. One task does both.
- **Bypass, don't tune, `analytics.py` (P1-1):** `services/groups.py` already computes the same metrics in fixed queries. Proxying beats optimizing a per-student loop.
- **Indexes before query rewrites where they overlap:** index-only PR first (zero behavior change, trivial rollback), then batched-query PRs that can rely on the new indexes.
- **S3 cutover gates multi-worker scale-out:** local-disk pin (`render.yaml` disk) makes >1 instance incorrect. No horizontal scaling until storage moves.
- **Explicitly deferred (DO NOT DO):** microservices, sharding/partitioning, Redis for app state, v1/v2 engine rewrite, bigger boxes for N+1s.

## Task List

### Phase 0 — Baseline & safety (measure before cutting)

- [ ] T0.1: Record baseline numbers (p50/p95 marking latency, queue drain for 50-job burst, analytics latency at current largest class, DB size, largest tables). Store in the PR descriptions that follow.
- [ ] T0.2: Hung-job runbook (manual fail+requeue SQL + worker restart steps) so Phase 1 has a backstop.

### Checkpoint: Baseline
- [ ] Baselines recorded; runbook reviewed by owner

### Phase 1 — DO NOW (P0s + hottest indexes + hottest lists)

- [ ] T1.1: Per-surface AI timeouts + split DB session around AI calls (P0-2)
- [ ] T1.2: Index PR — 4 divergent declarations + `past_paper_attempts`, `submission_files`, `assignments.group_id` (P1-4a)
- [ ] T1.3: Index PR — `group_members(student_id)`, `lessons(group_id,date)`, `readiness_history`, `ai_usage_events`, `assessment_scores` (P1-4b)
- [ ] T1.4: Proxy `analytics.py` through `groups.py` aggregates; cap + batch (P1-1)
- [ ] T1.5: Cursor pagination on review-queue + submissions-by-assignment (P1-6a)
- [ ] T1.6: Batch assessment create/list (auth `IN`, single topics fetch, GROUP BY counts) (P1-3)

### Checkpoint: P0s closed
- [ ] Hung-provider drill: stuck job dies at timeout, connection returns to pool, retry does not double-spend
- [ ] Full suite green (`pytest`, `ruff`, `mypy`, frontend `vitest`+`build` if touched); migration up→down→up verified on Postgres

### Phase 2 — BEFORE 500 (lanes, batch reads, memory, tokens, polling)

- [ ] T2.1: Worker lanes — marking/extraction lane vs fast lane, per-lane concurrency + priority (P0-1)
- [ ] T2.2: Batch CRM + readiness-summary reads (`Subject IN`, single `TopicReadiness IN`, grouped homework totals, cached boundaries) (P1-2)
- [ ] T2.3: Batch review-queue + submissions-list + lessons-list reads (GROUP BY counts, `selectinload`) (P1-3 cont.)
- [ ] T2.4: Stream file downloads; spool uploads; b64 off the loop; cap pages per marking call (P1-5)
- [ ] T2.5: Cap knowledge context with token budget + truncation (G)
- [ ] T2.6: Back off frontend marking/status polling (5 s → exponential, stop when settled) (P2)

### Checkpoint: 500-ready
- [ ] Load rehearsal: 100-submission burst drains within SLA; analytics p95 within target; worker RSS flat across burst

### Phase 3 — BEFORE 1000 (paginate all, S3, pool, retention, caps, clients)

- [ ] T3.1: Cursor pagination on remaining 23 unbounded lists + OpenAPI regen (P1-6)
- [ ] T3.2: S3 cutover (bucket, `STORAGE_BACKEND=s3`, remove disk pin, orphan cleanup) (H)
- [ ] T3.3: Pool hardening — explicit size/overflow, `pre_ping`, PgBouncer decision (E)
- [ ] T3.4: Retention/archival job for history/snapshots/factor-evals/usage/jobs (P1-6)
- [ ] T3.5: Per-surface AI concurrency caps + rate-limit handling; shared httpx/AI clients (G/P2)
- [ ] T3.6: Classroom incremental sync cursors + shared client (P2)
- [ ] T3.7: Debounce race guard — unique partial index / advisory lock on pending readiness jobs (F)

### Checkpoint: 1000-ready
- [ ] Multi-instance drill on staging (2 API + separate worker): no duplicate marking, no storage split-brain, pool math holds

### Phase 4 — BEFORE 5000 (read scale, autoscale, quotas)

- [ ] T4.1: Dashboard read replicas or CQRS read models
- [ ] T4.2: Worker autoscale by queue depth + per-org AI quotas
- [ ] T4.3: Re-audit against sections 30–32 of the report; promote/defer P2s on measured data

### Checkpoint: Complete
- [ ] All P0/P1 acceptance criteria met; report sections B–J signed off; ready for owner review

## Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Lane split changes job ordering semantics | Med | Keep FIFO within lane; ship T2.1 behind existing claim query; e2e burst test before merge |
| Session split around AI breaks handler atomicity | High | Commit pre-AI state explicitly; make post-AI writes idempotent (BE-6); failure-path tests per handler |
| S3 cutover orphans local files | High | Dual-read window + path migration script; cutover is its own PR + runbook, never bundled |
| Pagination changes frontend contracts | Med | OpenAPI regen in same PR (FE-4); frontend `schema.d.ts` diff is a CI gate |
| Index migrations lock hot tables | Med | `CREATE INDEX CONCURRENTLY`-aware review; deploy off-peak; up→down→up in CI |

## Open Questions

See report section K (instance size, students/tutor, submissions/wk, PDF sizes, AI p50/p95, rate limits, replica plans, retention law, marking SLA, Classroom usage, KB sizes). T0.1 answers the measurable half; the rest need the owner.

## Parallelization

- **Parallel-safe (after Phase 0):** T1.2 ∥ T1.4 ∥ T1.6 (different files); T2.2 ∥ T2.4 ∥ T2.5; T3.1 ∥ T3.4 ∥ T3.5.
- **Sequential:** T1.2 → T1.3 (migration chain); T1.5 → T3.1 (same endpoints); T3.2 → any multi-instance work; T1.1 → T2.1 (lanes assume bounded jobs).
- **Needs contract first:** T1.5/T3.1 pagination shape (cursor envelope) before frontend adopts it.
