# Task List: Backend Remediation

> **STANDING RULE — READ FIRST: NO PRODUCT OR ARCHITECTURE CHANGE WITHOUT THE OWNER'S EXPLICIT APPROVAL.**
> Any task whose title carries **[GATED — OWNER APPROVAL REQUIRED]** is a proposal only: do not cut a branch,
> write code, author a migration, or change config for it until the owner explicitly approves that task's scope
> and design. No agent approval counts — only the owner's. Everything else still ships via normal branch + PR review.
> Gated tasks: T1.4, T1.5, T2.1, T2.6, T3.1, T3.2, T3.3, T3.4, T3.5, T3.7, T4.1, T4.2.

Each task = one short-lived branch + one PR (repo rule). Verify commands assume `backend/` (pytest/ruff/mypy) and `frontend/` (vitest/build) working dirs. Migration tasks must pass CI's Alembic up → down → up on Postgres 16.

## Task T0.1: Record performance baselines

**Description:** Measure what "normal" looks like today so every later task can prove improvement: mean/p95 AI latency per surface (from `ai_usage_events`), time to drain a 50-job burst on staging, class-analytics latency at the largest real class, DB size + top-10 tables by rows, pool utilization under a burst.

**Acceptance criteria:**
- [ ] Numbers recorded (append to `avora-backend-forensic-audit-REPORT.md` §I or a `docs/` note in same PR as next change — prose-only doc edits may go direct to main)
- [ ] Burst-rehearsal procedure is repeatable (script or documented steps)

**Verification:**
- [ ] Queries run against staging replica, never prod writes
- [ ] Owner confirms the SLA targets (marking drain time, dashboard p95)

**Dependencies:** None
**Files likely touched:** none (read-only) or `docs/*`
**Estimated scope:** Small

## Task T0.2: Hung-job runbook

**Description:** Document the backstop for P0-2 until timeouts land: how to identify a stuck `running` job (`claimed_at`, `JOB_STALL_SECONDS`), SQL to mark it `failed`, worker restart steps, and how to confirm the pool recovered.

**Acceptance criteria:**
- [ ] Runbook covers R2/R4-relevant steps (migration-failure vs stuck-job distinguished)
- [ ] Drill on staging: stuck job cleared, queue resumes

**Verification:**
- [ ] Manual drill witnessed/pair-reviewed
- [ ] No code changes, so no suite gate

**Dependencies:** None
**Files likely touched:** `docs/volume-4-reliability-and-operations/14-operations-runbooks.md` (GOV-1: behavior docs updated with ops changes)
**Estimated scope:** Small

## Task T1.1: Per-surface AI timeouts + split session around AI calls (P0-2)

**Description:** Give every AI surface a bounded timeout and stop holding the DB session/transaction open across model latency: commit pre-AI state in each handler, run the AI call outside the session, then open a fresh session for post-AI writes (idempotent per BE-6).

**Acceptance criteria:**
- [ ] `structured_complete`/`text_complete` accept a per-surface timeout (e.g. 120–300 s marking/extraction, 60 s synthesis); a hung provider raises within bound — verified by fake-clock/hang test, never a real provider (QA-8)
- [ ] No handler holds a session across `await structured_complete` (grep-verified)
- [ ] Post-AI failure retries without double-spend (usage row written once; marking skips re-call when all questions finalized)

**Verification:**
- [ ] Tests pass: backend `pytest` incl. new hang/timeout tests driven via `process_one_job()` (QA-6), `structured_complete` monkeypatched at the calling module (QA-7)
- [ ] Lint/type: `ruff check`, `ruff format --check`, `mypy app/services app/schemas`

**Dependencies:** T0.2 (runbook as backstop)
**Files likely touched:**
- `backend/app/services/ai.py`
- `backend/app/workers/jobs.py`
- `backend/app/services/marking.py`, `extraction.py`, `syllabus_extraction.py`, `reports.py`, `readiness_v2_ai.py`, `narrative.py`
- `backend/tests/test_*.py`
**Estimated scope:** Large → split per-handler follow-ups if it exceeds ~5 files per PR (stack small PRs: ai.py first, then handlers)

## Task T1.2: Index PR, batch A (P1-4a)

**Description:** Hand-written sequential migration (DB-15/16/17: `batch_alter_table` + NAMING, working downgrade) plus model-side declarations (DB-12) for: the 4 divergent indexes (`evidence`, `factor_evaluations`, `readiness_snapshots`, `mark_override_audit`), `past_paper_attempts(student_id,past_paper_id)`, `submission_files(submission_id)`, `assignments(group_id)`.

**Acceptance criteria:**
- [ ] `EXPLAIN` on the hottest queries (v2 factor reads, evidence-by-topic, review-queue join) uses the new indexes
- [ ] Test schema and prod schema agree on these indexes (DB-12 closed for batch A)

**Verification:**
- [ ] CI migration job up → down → up green; `pytest` green; `ruff` clean

**Dependencies:** None (zero behavior change — safe to land first)
**Files likely touched:**
- `backend/alembic/versions/00NN_*.py` (next sequence number, chained `down_revision`)
- `backend/app/models/homework.py`, `readiness.py`, `readiness_v2.py`
**Estimated scope:** Small

## Task T1.3: Index PR, batch B (P1-4b)

**Description:** Same migration discipline as T1.2 for: `group_members(student_id)` (or `(student_id,group_id)`), `lessons(group_id,date DESC)`, `readiness_history(student_id,subject_id,recorded_at)`, `ai_usage_events(organization_id,created_at)`, `assessment_scores(student_id)` (+ assessment-side as needed).

**Acceptance criteria:**
- [ ] CRM, trend, analytics, and usage-analytics queries show index usage on `EXPLAIN`
- [ ] No full-seq-scan remains on any per-request hot path at 10k-row fixture scale

**Verification:**
- [ ] CI migration job green; `pytest` green

**Dependencies:** T1.2 (migration chain order)
**Files likely touched:**
- `backend/alembic/versions/00NN_*.py`
- `backend/app/models/groups.py`, `lessons.py`, `readiness.py`, `ai_usage.py`
**Estimated scope:** Small

## Task T1.4: Bypass `analytics.py` via `groups.py` aggregates (P1-1) **[GATED — OWNER APPROVAL REQUIRED]**

**Description:** Route class-analytics reads (and `class_brief`'s analytics portion) through the existing fixed-query helpers (`weighted_learner_scores`, `class_health`, `summaries`) instead of the `5+2N` per-student loop; keep response shape stable or version it with OpenAPI regen (FE-4/API-15).

**Acceptance criteria:**
- [ ] Class page cost is O(1) in roster size: measured ≤ ~12 queries at N=10 and N=200 fixture
- [ ] Numbers match old implementation within tolerance on seed data (or documented intentional difference)
- [ ] If response schema changed: `openapi.json` + `schema.d.ts` regenerated in same PR

**Verification:**
- [ ] `pytest` incl. parity test (old vs new on seeded class) + query-count assertion
- [ ] Frontend `vitest` + `npm run build` if types regenerated

**Dependencies:** T1.2 (indexes the new aggregates rely on)
**Files likely touched:**
- `backend/app/api/analytics.py`, `backend/app/api/groups.py`, `backend/app/services/groups.py`
- `backend/tests/test_analytics*.py`, `frontend/openapi.json`, `frontend/src/api/schema.d.ts`
**Estimated scope:** Medium

## Task T1.5: Cursor pagination — review-queue + submissions-by-assignment (P1-6a) **[GATED — OWNER APPROVAL REQUIRED]**

**Description:** Add keyset (cursor, not OFFSET) pagination to the two fastest-growing tutor lists; define the cursor envelope contract the frontend will reuse in T3.1.

**Acceptance criteria:**
- [ ] Both endpoints accept `cursor` + `limit` (bounded max, e.g. 50); default page bounded
- [ ] Response includes `next_cursor`; empty page terminates
- [ ] OpenAPI + `schema.d.ts` regenerated in same PR

**Verification:**
- [ ] `pytest` pagination tests (first page, walk full list via cursors, no dupes/skips under insert); `ruff`/`mypy` clean; frontend build green

**Dependencies:** None (parallel-safe with T1.2/T1.4)
**Files likely touched:**
- `backend/app/api/submissions.py`, `backend/app/schemas/*.py`
- `backend/tests/test_submissions*.py`, `frontend/openapi.json`, `frontend/src/api/schema.d.ts`
**Estimated scope:** Medium

## Task T1.6: Batch assessment create/list (P1-3)

**Description:** Remove per-score/per-assessment queries: batch tutor-auth into one `subject IN` check, fetch topics once, replace per-row counts with `GROUP BY`; keep authorization correctness (never weaken the gate to save queries).

**Acceptance criteria:**
- [ ] 100-score create: ≤ ~10 queries (was 100–200); list: 2–3 queries (was 1+N)
- [ ] Negative auth tests still pass (wrong tutor, other org — QA-12)

**Verification:**
- [ ] `pytest` incl. query-count + negative-auth tests; `ruff`/`mypy` clean

**Dependencies:** None
**Files likely touched:**
- `backend/app/api/assessments.py`, `backend/tests/test_assessments*.py`
**Estimated scope:** Small

## Task T2.1: Worker lanes + per-lane concurrency (P0-1) **[GATED — OWNER APPROVAL REQUIRED]**

**Description:** Split the single FIFO into a slow lane (marking, extraction, syllabus) and a fast lane (readiness, reports, narratives, sweep), each with its own claimant loop and concurrency bound, reusing the `SKIP LOCKED` claim. FIFO preserved within a lane.

**Acceptance criteria:**
- [ ] 1 slow marking job no longer blocks fast-lane drain (rehearsed: 1×long + 100 fast → fast lane drains in minutes)
- [ ] Lane of a job is deterministic from job type; unknown types fail closed to a default lane, never dropped
- [ ] `/health/ready` reports per-lane depth

**Verification:**
- [ ] `pytest` lane/starvation tests via `process_one_job()` per lane; concurrent-claim test (two claimants never take same row); full suite green

**Dependencies:** T1.1 (bounded jobs — lanes assume jobs die at timeout, not hang forever)
**Files likely touched:**
- `backend/app/workers/jobs.py`, `backend/app/workers/runner.py`, `backend/app/workers/handlers.py`, `backend/app/main.py`
- `backend/tests/test_worker*.py`, `test_jobs*.py`
**Estimated scope:** Large → split: (a) lane routing + claim, (b) runner/supervision + health

## Task T2.2: Batch CRM + readiness-summary reads (P1-2)

**Description:** Collapse the ~85-query CRM open and per-subject fan-out: `Subject IN` batch, single `TopicReadiness … IN`, one homework-totals `GROUP BY`, cached grade boundaries per request.

**Acceptance criteria:**
- [ ] CRM open ≤ ~12 queries at E=5/S=5/H=20 fixture; student readiness ≤ ~8 at S=5
- [ ] Returned numbers byte-identical to pre-change on seed data

**Verification:**
- [ ] `pytest` parity + query-count tests; `ruff`/`mypy` clean

**Dependencies:** T1.2/T1.3 (indexes)
**Files likely touched:**
- `backend/app/services/student_crm.py`, `readiness_summary.py`, `readiness_summary_v2.py`, `averaging.py`
- `backend/tests/test_crm*.py`, `test_readiness*.py`
**Estimated scope:** Medium

## Task T2.3: Batch review-queue + submissions-list + lessons-list reads

**Description:** Finish P1-3 on the read side: `GROUP BY` marks/remarks counts, `selectinload` lesson topics, single totals aggregate per assignment view.

**Acceptance criteria:**
- [ ] Review-queue R=100: ≤ ~5 queries (was ~201); submissions-by-assignment N=100: ≤ ~6; lessons L=100: ≤ ~3

**Verification:**
- [ ] `pytest` query-count tests; negative-auth tests intact (QA-12)

**Dependencies:** T1.5 (same endpoints — build on the paginated shape)
**Files likely touched:**
- `backend/app/api/submissions.py`, `backend/app/api/lessons.py`, `backend/tests/test_*.py`
**Estimated scope:** Medium

## Task T2.4: Stream files; b64 off the loop; cap marking pages (P1-5)

**Description:** Stream downloads (`FileResponse`/chunked S3) instead of buffering; spool uploads to disk; move base64 encode/decode to a thread; cap pages attached per marking call with overflow behavior (extra pages queued or rejected with clear error — owner picks).

**Acceptance criteria:**
- [ ] 20 MB download holds ~flat RSS (no whole-file buffer); marking RSS bounded per job at 5-page fixture
- [ ] No `await file.read()` whole-file pattern remains on request/worker paths (grep-verified)

**Verification:**
- [ ] `pytest` streaming + memory-smoke tests; `ruff` clean (ASYNC rules)

**Dependencies:** None (parallel-safe)
**Files likely touched:**
- `backend/app/services/storage.py`, `backend/app/api/file_responses.py`, `backend/app/services/ai.py`, `backend/app/services/marking.py`
- `backend/tests/test_storage*.py`
**Estimated scope:** Medium

## Task T2.5: Cap knowledge context (token budget)

**Description:** Bound `build_tutor_context` with a per-call token/char budget, relevance ordering, and truncation marker; keep prompt-cache-friendly ordering (stable content last).

**Acceptance criteria:**
- [ ] 1000-entry tutor fixture produces bounded prompt (budget enforced, logged when truncated)
- [ ] Prompt version bumped if template text changes meaningfully (AI-7); prompts stay in `prompts.py` (AI-6)

**Verification:**
- [ ] `pytest` budget/truncation tests; AI surfaces' token counts asserted from `ai_usage_events` in fake-AI tests

**Dependencies:** None
**Files likely touched:**
- `backend/app/services/knowledge.py`, `backend/app/services/prompts.py`, `backend/tests/test_knowledge*.py`
**Estimated scope:** Small

## Task T2.6: Back off frontend polling **[GATED — OWNER APPROVAL REQUIRED]**

**Description:** Replace fixed 2.5–5 s status polling (marking, extraction, reports, submissions list) with exponential backoff + stop-when-settled; keep TanStack Query as the single data layer (FE-6).

**Acceptance criteria:**
- [ ] Steady-state polling traffic during a 10-min marking job drops ≥ 70% vs baseline
- [ ] Fresh states still surface within ~10 s of settling

**Verification:**
- [ ] Frontend `vitest` + `eslint --max-warnings 0` + `prettier --check` + `npm run build`

**Dependencies:** None
**Files likely touched:**
- `frontend/src/tutor/AssignmentDetailPage.tsx`, `SubmitHomeworkPage.tsx`, `SitPastPaperPage.tsx`, `ReportsPanel.tsx`, `SyllabusUploadPage.tsx`
**Estimated scope:** Small

## Task T3.1: Cursor pagination on remaining lists **[GATED — OWNER APPROVAL REQUIRED]**

**Description:** Extend the T1.5 cursor envelope to all remaining unbounded collection GETs (target: 0 unbounded); regenerate OpenAPI + `schema.d.ts` in the same PR(s); update frontend callers page-walk where needed.

**Acceptance criteria:**
- [ ] Audit grep: zero collection GETs without `cursor`/`limit`
- [ ] Same-PR type regen; frontend paginated views walk to completion in tests

**Verification:**
- [ ] Backend `pytest`; frontend `vitest` + `build` (the only type check); CI API-freshness check green

**Dependencies:** T1.5 (envelope contract), T2.3 (batched reads underneath)
**Files likely touched:**
- `backend/app/api/*.py` (remaining routers), schemas, tests; `frontend/openapi.json`, `schema.d.ts`, list callers
**Estimated scope:** Large → split per-router PRs (≤5 files each)

## Task T3.2: S3 cutover + remove disk pin **[GATED — OWNER APPROVAL REQUIRED]**

**Description:** Provision bucket, set `STORAGE_BACKEND=s3`, migrate existing `/data` objects with dual-read window, remove the single-instance-pinning disk, add orphan-file cleanup. Own runbook; never bundled with other changes.

**Acceptance criteria:**
- [ ] All pre-cutover files readable post-cutover (checksum spot-check)
- [ ] API runs with no persistent disk; two instances serve downloads concurrently
- [ ] Orphan sweep deletes unreferenced objects older than N days (owner picks N)

**Verification:**
- [ ] Staging cutover rehearsal incl. rollback; `pytest` storage-backend tests (local + s3 paths)

**Dependencies:** T2.4 (streaming first — don't move buffering to S3)
**Files likely touched:**
- `backend/app/services/storage.py`, `render.yaml`, deploy docs, migration script (one-shot, `seed/`-style)
**Estimated scope:** Medium

## Task T3.3: Pool hardening **[GATED — OWNER APPROVAL REQUIRED]**

**Description:** Explicit `pool_size`/`max_overflow`/`pool_timeout` + `pre_ping`, sized from measured concurrency; decide PgBouncer (yes/no) with Deploy math N×conns ≤ pg limit; document the 6-instance ceiling until then.

**Acceptance criteria:**
- [ ] DB-restart drill: first request after restart succeeds (no stale-conn errors)
- [ ] Pool-exhaustion drill degrades with clear 503s, never hangs past `pool_timeout`

**Verification:**
- [ ] `pytest` pool-timeout tests; staging restart drill

**Dependencies:** T3.2 (pool math changes with instance count)
**Files likely touched:**
- `backend/app/db.py`, `backend/app/config.py`, `render.yaml`, `docs/volume-3-platform-engineering/08-infrastructure-and-deployment.md`
**Estimated scope:** Small

## Task T3.4: Retention/archival job **[GATED — OWNER APPROVAL REQUIRED]**

**Description:** Retention policy + scheduled job (owner answers report §K first: legal minimums) for readiness history, snapshots, factor evals, `ai_usage_events`, terminal jobs, stale narratives. Archive-then-delete; never hard-delete without archive.

**Acceptance criteria:**
- [ ] Policy table (per-table retention, archive location) approved by owner
- [ ] Dry-run mode logs what would be deleted; first production run reviewed

**Verification:**
- [ ] `pytest` retention tests (boundary ages kept/deleted correctly); job idempotent on re-run (BE-6)

**Dependencies:** Report §K answers (retention law)
**Files likely touched:**
- `backend/app/services/retention.py` (new), `backend/app/workers/handlers.py`, tests
**Estimated scope:** Medium

## Task T3.5: AI concurrency caps + shared clients **[GATED — OWNER APPROVAL REQUIRED]**

**Description:** Per-surface in-flight caps with queueing + provider rate-limit handling (429/backoff, no thundering retry); share httpx/Anthropic/Gemini clients with explicit timeouts from T1.1.

**Acceptance criteria:**
- [ ] Burst of 200 marking jobs never exceeds cap (measured concurrent provider calls ≤ cap)
- [ ] 429s back off and complete; no duplicate side effects on retry

**Verification:**
- [ ] `pytest` with fake transport (429 then success); never real providers (QA-8)

**Dependencies:** T1.1 (timeouts), T2.1 (lanes define where caps live)
**Files likely touched:**
- `backend/app/services/ai.py`, worker lane code, tests
**Estimated scope:** Medium

## Task T3.6: Classroom incremental sync

**Description:** Per-course sync cursors (only new/changed coursework/submissions), shared httpx client with pool + timeouts; batch profile/metadata fetches where the API allows.

**Acceptance criteria:**
- [ ] Second sync of unchanged course issues O(1) API calls, not O(submissions)
- [ ] HTTP fan-out per new submission halved or better vs baseline

**Verification:**
- [ ] `pytest` with mocked Google transport; no live Google calls

**Dependencies:** T3.5 (shared client pattern)
**Files likely touched:**
- `backend/app/services/google_classroom.py`, `backend/app/models/classroom.py` (+ migration if cursor columns added), tests
**Estimated scope:** Medium

## Task T3.7: Debounce race guard **[GATED — OWNER APPROVAL REQUIRED]**

**Description:** Make `enqueue_readiness_v2_debounced` (and narrative `_enqueue_one`) race-safe: unique partial index on pending (student, subject) jobs or advisory-lock insert; concurrent evidence commits collapse to one job.

**Acceptance criteria:**
- [ ] 50 concurrent commits for one (student, subject) produce exactly 1 pending job (concurrency test)
- [ ] Handler idempotency retained as defense-in-depth (BE-6)

**Verification:**
- [ ] `pytest` concurrent-enqueue test (real threads/tasks against Postgres-style locking; document SQLite limits)

**Dependencies:** None (needs care with test-vs-prod locking semantics)
**Files likely touched:**
- `backend/app/services/readiness_v2_ai.py`, `backend/app/services/narrative.py`, migration (if index), tests
**Estimated scope:** Small

## Task T4.1: Dashboard read scale **[GATED — OWNER APPROVAL REQUIRED]**

**Description:** Read replicas or CQRS read models for dashboards/analytics — only if T0–T3 measurements still show DB-bound dashboards at 1000-student fixtures. Decision gate, not a foregone build.

**Acceptance criteria:**
- [ ] Gate: measured dashboard p95 still > SLA after T1.4/T2.2; else task closed as P4 with evidence

**Verification:** Per chosen design
**Dependencies:** T1.4, T2.2, T3.3 + measured data
**Files likely touched:** TBD by design
**Estimated scope:** Large (design doc first)

## Task T4.2: Worker autoscale + per-org AI quotas **[GATED — OWNER APPROVAL REQUIRED]**

**Description:** Scale lane workers by queue depth; enforce per-organization AI spend/call quotas with clear "quota exhausted" UX instead of silent stalls.

**Acceptance criteria:**
- [ ] Sustained backlog grows workers and drains within SLA; quota breach returns explicit error, recorded in `ai_usage_events` reporting

**Verification:**
- [ ] Staging autoscale drill; quota tests with fake AI

**Dependencies:** T2.1, T3.2, T3.5
**Files likely touched:** worker deploy config, `ai.py` metering, quota service (new), tests
**Estimated scope:** Large → design doc first, then slice

## Task T4.3: Re-audit and re-prioritize

**Description:** Re-run report sections 30–32 measurements at the new head; promote/defer remaining P2s on data; close or restate anything the code now contradicts (GOV-3: fix code, supersede rule, or record Known Gap).

**Acceptance criteria:**
- [ ] Updated bottleneck table (100 → 10k) with measured numbers; roadmap v2

**Verification:** Owner review
**Dependencies:** All prior phases
**Files likely touched:** `docs/` (GOV-1 updates in same round)
**Estimated scope:** Small
