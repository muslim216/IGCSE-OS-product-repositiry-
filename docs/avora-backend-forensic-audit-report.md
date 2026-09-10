# AVORA BACKEND — ADVERSARIAL FORENSIC PERFORMANCE & SCALABILITY AUDIT

**Date:** 2026-09-05 · **Scope:** `backend/` (FastAPI + SQLAlchemy + Postgres + worker + AI + storage) · **Method:** evidence-first, code-wins.
**Standing rule honored:** docs/comments/tests treated as hypotheses; every claim verified against executable code, migrations, and deploy config.
**Local only:** this file is untracked local output. NOT committed, NOT pushed, NO PR. Do not commit it without an explicit decision.

> **GOVERNANCE — OWNER APPROVAL REQUIRED. READ FIRST.**
> This report is **diagnostic only**: it authorizes zero changes to the product or the architecture.
> Per standing owner rule, **nothing described or implied in this report may be designed, built,
> migrated, or merged without the owner's explicit approval of that specific item first.**
> The follow-up build order in `tasks/plan.md` / `tasks/todo.md` tags every approval-gated item
> **[GATED]**. Ungated items still follow normal PR review. No agent approval counts — only the owner's.

---

## 0. Backend map (verified)

Tech verified against `backend/pyproject.toml:6-32`: Python ≥3.11, FastAPI, uvicorn, SQLAlchemy[asyncio] 2.x, asyncpg, aiosqlite (tests), Alembic, Pydantic v2 + pydantic-settings, python-multipart, PyJWT, bcrypt, anthropic SDK, google-genai SDK, httpx, cryptography, Pillow + pillow-heif, boto3 (lazy import), redis lib (rate-limit only). Postgres 16 (`docker-compose.yml`, Render `basic-256mb`). Single Render web service + 10 GB persistent disk (`render.yaml:18-55`).

```
HTTP request → FastAPI router (25 routers, 23 mounted; classroom+knowledge hidden)
  → deps/auth (api/deps.py: TutorUser/StudentUser signature gates; user.organization_id per-query scoping)
  → service (app/services/, 28 modules)
  → SQLAlchemy AsyncSession → asyncpg → PostgreSQL

HTTP request → job row INSERT (jobs table)
  → worker_loop polls every 2s → claim (FOR UPDATE SKIP LOCKED) → handler(session, payload)
  → AI (Anthropic/Gemini via services/ai.py) / storage (local disk or S3) / DB writes
```

Major pipelines: assignment extraction → publish → student submission → AI marking → auto-finalize or tutor review → Evidence → v1 recompute + v2 debounced synthesis → snapshots → narratives/reports/briefs; plus syllabus extraction, past-paper extraction/marking (same Submission+QuestionMark path, PROD-9), Google Classroom sync, uploads/downloads, analytics, tutor/student/parent dashboards, review queue.

---

## A. EXECUTIVE VERDICT

**Is it scalable? No — it is a well-built single-tutor product with a hard serial core.**

The bottleneck sequence, each verified:

1. **Worker concurrency = 1** (`app/workers/jobs.py:645-681` single `while True: process_one_job`; `Dockerfile:31` single uvicorn, no `--workers`; `main.py:73-75` one `create_task`). All AI workloads — marking (32k tokens), extraction (16k), reports (2k), readiness synthesis (2k), narratives — share one FIFO by `id`. One slow marking job stalls everything. `JOB_STALL_SECONDS=900` (`jobs.py:51`) only relabels health; nothing preempts.
2. **Every handler holds its DB session/transaction open across an unbounded AI call** (`jobs.py:483-485`), and **no AI call has any timeout** (`ai.py:278,305,344,371` — no `timeout=`, no `wait_for`, no retry; only job-level `MAX_ATTEMPTS=2`). A hung provider pins a pool connection indefinitely; retry discards the AI work and pays twice.
3. **Read/analytics N+1s grow with roster size.** `api/analytics.py:49-58` = `5+2N` (N=100 → 205 queries; N=1000 → 2005). CRM open ≈ 85 queries. `list_assessments` N+1, `create_assessment` 1/score, review-queue `1+2R`, submissions-by-assignment `4+N_settled`. Fixed-shape replacements exist (`services/groups.py`, `services/today.py`) but the bad paths are still live, and `class_brief` re-enters the bad one.
4. **Zero pagination: 0 paginated vs 28 unbounded collection GETs** (only cap: CRM `.limit(20)`).
5. **Pool = implicit defaults 5+10=15 conns/process** (`db.py:9-18` returns `{}` for Postgres; probe-confirmed; `pre_ping=False, recycle=-1`). Safe at 1 instance vs ~97-conn `basic-256mb`; fatal at ~6 instances. No PgBouncer.
6. **Index gaps on the hottest FKs** (`PastPaperAttempt` both columns unindexed; `SubmissionFile.submission_id`, `Assignment.group_id`, `AssessmentScore.student_id` unindexed; 4 prod-only indexes missing from models/test schema).
7. **Whole-file buffering + base64 amplification** (~330 MB transient per 5-page 20 MB marking job), no streaming downloads.

**Genuinely dangerous:** serial worker + no AI timeout + transaction-held-open + ~330 MB/job transients + 2 h orphan reclaim. A whole-class same-evening submission burst queues hours of serial AI latency while "being_marked" polling (3–5 s `refetchInterval`) hammers the backend.

**Merely ugly but harmless:** per-request httpx/Google clients, per-call AI clients, bcrypt on the loop (~100 ms, low-frequency auth path), base64 on the loop, missing `pre_ping`, `Unique`-covered topic lookups.

**Realistic scale today:** 1 tutor × 50–100 students works. 300–500 = painful marking delays + analytics timeouts. 1,000 = queue collapse under any burst. 5k–10k needs architectural change, not bigger instances.

---

## B. CRITICAL FINDINGS (P0/P1 — file, line, evidence, impact, threshold, fix)

### P0-1 — Serial worker, FIFO head-of-line blocking
- **Files:** `backend/app/workers/jobs.py:645-681`, `backend/app/workers/runner.py:32-47`, `backend/app/main.py:73-75`, `backend/Dockerfile:31`, `backend/app/workers/__main__.py:36`
- **Evidence:** one `while True: process_one_job()`; no semaphore/gather/pool; one uvicorn process; supervisor only restarts the same loop.
- **Impact:** `1×10-min marking + 100×readiness` → readiness waits ~10 min. `100 markings × 60–180 s` → 1.6–5 h drain. Reports wait behind marking.
- **Threshold:** hurts at ~50 concurrent submissions; breaks at 100+.
- **Fix:** separate queues/pools by workload (marking vs fast jobs) or N parallel claimants over `SKIP LOCKED`; per-type concurrency + priority + stall-kill. Cost: medium. Do NOT just add uvicorn `--workers` on local disk (duplicates worker + storage split-brain).

### P0-2 — No AI timeout anywhere; transaction held across AI call
- **Files:** `backend/app/services/ai.py:278,305,344,371` (zero `timeout=`), `backend/app/workers/jobs.py:483-485` (session spans `reads → AI → writes`); handlers `marking.py:331`, `extraction.py:121,224`, `syllabus_extraction.py:70`, `reports.py:164`, `readiness_v2_ai.py:320`
- **Evidence:** `timeout` grep in `ai.py` = zero hits; claim COMMITs before handler, but handler session stays open through unbounded model latency.
- **Impact:** hung provider pins pool conn forever; stall label doesn't kill; post-AI failure discards work and re-calls (double spend; marking skips re-call only if *all* questions finalized, `marking.py:276-279`).
- **Threshold:** any provider hang; probabilistic, worse at scale.
- **Fix:** bounded timeout per surface (e.g. 120–300 s marking/extraction, 60 s synthesis) + SDK timeout; commit pre-AI state / split sessions pre/post AI; idempotent usage record. Cost: low-medium.

### P1-1 — `group_analytics` 5+2N live on class page + class brief
- **File:** `backend/app/api/analytics.py:33-58,108-119`
- **Evidence:** `get Group + get Subject + members + topics + per-student get+TopicReadiness + 1 agreement join`. N=10→25, 100→205, 1000→2005.
- **Threshold:** slow at N=50–100; timeout-risk at 200+.
- **Fix:** route class surfaces through `services/groups.py:weighted_learner_scores/class_health` (1 grouped query); `today.py` proves the pattern. Delete or proxy `analytics.py`. Cost: low.

### P1-2 — CRM open ~85 queries; per-subject readiness fan-out
- **Files:** `backend/app/services/student_crm.py:76-160`, `readiness_summary.py:210-217`, `readiness_summary_v2.py:89-182,192-196`, `averaging.py:100,119`
- **Evidence:** profile 1 + enrollments 1 + E `get(Subject)` + S×(5–8) + homework 1+2H (H≤20) + notes + comms.
- **Impact:** every tutor CRM open ≈ 85 queries; student readiness S=5 → 20–40 + v1 fallback.
- **Fix:** batch `Subject IN`, single `TopicReadiness … IN`, one homework-totals GROUP BY; cache boundaries. Cost: medium.

### P1-3 — Assessment create/list N+1; review-queue 1+2R; submissions list 4+N
- **Files:** `assessments.py:67-68,74,110,153-156`; `submissions.py:432-438,535-543,455-466`
- **Evidence:** `_tutor_teaches` scalar per score; identical topics query per overall score; `count` per assessment; per-row marks count + remarks.
- **Threshold:** 100 scores → 100–200 queries in one POST; R=100 → 201 queries.
- **Fix:** batch auth (`subject IN`), single topics fetch, `GROUP BY` counts. Keep auth correctness. Cost: low.

### P1-4 — Missing indexes on hot paths (+4 prod-only indexes absent from models)
- **Files:** `readiness_v2.py:139-140` (PastPaperAttempt both cols), `homework.py:195` (SubmissionFile), `homework.py:53` (Assignment.group_id), `readiness.py:141-144` (AssessmentScore), `groups.py:41` (wrong-column-first unique); `lessons` (group_id,date); `readiness_history`; `ai_usage_events`; migrations `0004:44`, `0016:169,194`, `0019:51` vs models.
- **Fix:** ~8 single/compound indexes via hand-written sequential migrations (`batch_alter_table+NAMING`, working downgrade, CI up→down→up); declare the 4 divergent indexes in models (DB-12). Cost: low, high benefit.

### P1-5 — Whole-file buffering + base64 amplification; no streaming downloads
- **Files:** `storage.py:368,396,286,214`, `ai.py:169,199`, `marking.py:315`, `file_responses.py:52,60-67`
- **Evidence:** `await file.read()` whole 20 MB; `b64encode` ×1.37; `gather` all pages then encode: 5×20 MB → ~140 raw + ~190 b64 ≈ 330 MB transient/job; S3 `Body.read()` whole; `Response(content=data)`.
- **Threshold:** 20 concurrent 20 MB docs → GBs RSS + loop CPU (b64 sync on loop).
- **Fix:** stream uploads to disk, stream downloads (`FileResponse`/chunked S3), b64 in thread, cap pages per call. Cost: medium.

### P1-6 — Unbounded lists (28) + append-only history/factors/snapshots/usage/jobs
- **Evidence:** zero `limit/offset/page` params; history never deleted (`readiness.py:262-271`; `readiness_v2.py:328-418` T+6 rows/run).
- **Threshold:** 1k students × 5 subjects × weekly recompute → millions of rows/year.
- **Fix:** cursor pagination on 5 growth-risk lists first; retention/archival policy. Cost: medium.

### P2/P3/P4 (summarized)
- **P2:** Google Classroom per-submission HTTP fan-out (~3 HTTP + 2 DB per turned-in submission; `google_classroom.py:284-385`); per-call AI/httpx clients (TLS per job); unbounded knowledge context (token blowup); `pre_ping=False`/no recycle (first request after DB restart fails); frontend polling fan-out (5 s submissions poll, 2.5–4 s status polls).
- **P3:** bcrypt on loop (~100 ms, auth-frequency only — wrap in `to_thread`, cheap); shared-default-executor contention (S3+HEIC+file IO); `Topic.parent_id`/reverse-lookup indexes; `Unique`-covered but fragile eager loads (`groups.py:265`, `today.py:155,185`).
- **P4 (explicitly not worth fixing yet):** JWT/sha256/json.loads micro-costs; `model_pricing` lru_cache; per-file MIME sniffing; table partitioning (volume doesn't justify it); microservice split.

---

## C. N+1 INVENTORY (confirmed)

| # | File:function:line | Pattern | N=10 | N=100 | N=1000 | Fix |
|---|---|---|---|---|---|---|
| 1 | `api/analytics.py:group_analytics:49-58` | `get User + TopicReadiness`/student | 25 | 205 | 2005 | use `groups.py` grouped aggregates |
| 2 | `api/assessments.py:create:67-68` | `_tutor_teaches` scalar/score | 10–20 | 100–200 | 1000–2000 | batch `subject IN` auth |
| 3 | `api/assessments.py:list:153-156` | `count`/assessment | 11 | 101 | 1001 | `GROUP BY` counts |
| 4 | `api/submissions.py:review-queue:535-543` | marks count + remarks/row | 21 | 201 | 2001 | `GROUP BY` + batched remarks |
| 5 | `api/submissions.py:list-by-assignment:432-438` | totals/settled sub | ~14 | ~104 | ~1004 | one `GROUP BY` |
| 6 | `services/readiness_summary.py:210` | 6q/subject | S=3→18 | — | — | batch subjects/topics/readiness |
| 7 | `services/student_crm.py:85-86,119-130` | get/enrollment + 2/homework row | ~85/CRM | — | — | `IN` + grouped totals |
| 8 | `services/evidence.py:64-76` | topic lookup/question | 1+Q | — | — | single topic-map query |
| 9 | `services/readiness_v2.py:84-100,176-187` | 1 join/topic + 2/settled HW | 6+T+2H | — | — | batched joins |
| 10 | `api/lessons.py:98` | topics/lesson | 11 | 101 | 1001 | `selectinload` collection |
| 11 | `google_classroom.py:284-385` | ~3 HTTP + 2 DB/submission | 30 HTTP | 300 HTTP | 3000 HTTP | incremental cursors, shared client |

No active lazy-relationship N+1 (all `selectinload`); fragile-but-current: `groups.py:265`, `today.py:155,185`, `auth.py:236`.

---

## D. QUERY COMPLEXITY TABLE (major endpoints)

| Endpoint | Base | N=10 | N=100 | N=1000 | Ext calls | Complexity |
|---|---|---|---|---|---|---|
| `GET /today` | 11 | 11 | 11 | 11 | 0 | O(1) |
| `GET /today/classes/{id}` | 11 | 11 | 11 | 11 | 0 | O(1) |
| `GET /analytics/groups/{id}` | 5+2N | 25 | 205 | 2005 | 0–1 AI (brief) | O(N) |
| `GET /students/{id}/crm` | 6+E+5S+2H | ~85 | ~85+ | — | 0 | O(S+H) |
| `GET /readiness/students/{id}` | 1+6S | ~31 (S=5) | — | — | 0 | O(S) |
| `GET /readiness/…/trend` | 1+3S | ~16 | — | — | 0 | O(S) |
| `GET /me/assignments` | 5 | 5 | 5 | 5 | 0 | O(1) ✅ |
| `GET /assignments/{id}/submissions` | 4+N | 14 | 104 | 1004 | 0 | O(N) |
| `GET /submissions/review-queue` | 1+2R | 21 | 201 | 2001 | 0 | O(R) |
| `POST /assessments` (S scores) | S–2S | 10–20 | 100–200 | 1000–2000 | +v2 enqueues | O(S) |
| `GET /assessments` | 1+N | 11 | 101 | 1001 | 0 | O(N) |
| `POST /reports/generate` | ~4 | ~4 | ~4 | ~4 | 1 AI async | O(1) req; O(S) job |

Readiness complexity: one submission → 1 v1 recompute (5q/subject, O(S×(T+E))) + ≤1 v2 synthesis (6+T+2H queries + 1 AI call/subject) + narrative enqueue. NOT O(1); roughly O(subjects × (topics + evidence)) per submission.

---

## E. DATABASE / INDEX REPORT

- **Engine:** `app/db.py:18` with `{}` → QueuePool 5+10=**15** conns/process, timeout 30 s, `pre_ping=False`, `recycle=-1`. 1 instance: 15 ≪ 97 (`basic-256mb`) — safe. N×15 ≤ 97 → **max ~6 instances**. No PgBouncer. Migrations use NullPool (correct).
- **Test/prod divergence (DB-12):** `ix_evidence_student_topic` (`0004:44`), `ix_factor_evaluations_run_student_subject` (`0016:169`), `ix_readiness_snapshots_student_subject` (`0016:194`), `ix_mark_override_audit_qm` (`0019:51`) exist in migrations, absent from models → test plans ≠ prod plans; only CI's Postgres migration job exercises them.
- **Add:** `past_paper_attempts(student_id,past_paper_id)` (hottest v2 input, zero index); `submission_files(submission_id)`; `assignments(group_id)`; `assignment_questions(assignment_id)`; `group_members(student_id)` or `(student_id,group_id)`; `lessons(group_id,date DESC)`; `readiness_history(student_id,subject_id,recorded_at)`; `ai_usage_events(organization_id,created_at)`; `assessment_scores(student_id)`; model-side declarations for the 4 divergent indexes. FK ≠ index — verified throughout.

---

## F. WORKER / QUEUE REPORT

Concurrency **1** per process (serial `worker_loop`, one uvicorn, one in-process task). Claim atomic (`FOR UPDATE SKIP LOCKED`, commit-before-run — correct). Retry once after 60 s (`MAX_ATTEMPTS=2`); then `failed` unwatched. Orphan reclaim = missing heartbeat + 2 h age (duplicate-safe, 2 h blackout). Poll 2 s. Debounce `enqueue_readiness_v2_debounced:110-120` is check-then-insert **without constraint** → concurrent commits duplicate jobs (idempotent handlers: wasteful, not corrupt). Narrative margin +900 s; sweep cap 250/24 h. Starvation scenarios verified: 1×10-min marking blocks 100 fast jobs; 100 markings × 60–180 s = 1.6–5 h; report behind marking waits hours. Needs workload-separated pools before 500 students.

---

## G. AI PIPELINE REPORT

Max-output: marking 32000, extraction/syllabus 16000, readiness/reports 2000, narrative 400. Routing (`resolve_surface`) and metering (`record_usage`, NULL-when-unpriced) correct. **No timeout/retry/client-reuse on any surface**; per-call SDK clients. Knowledge context unbounded (`knowledge.py:22-50`) — 100/1000 entries = token blowup on every call. File amplification: §B-P1-5. Queue math `T ≈ jobs × mean_latency / 1`: 10×60 s = 10 min; 100×60 s = 100 min; 500×60 s = 8.3 h; 1000×60 s = 16.7 h (use 30/60/180 s sensitivity — latency must be measured). **Dominant bottleneck: worker concurrency (1), then provider latency.** DB/CPU/storage secondary.

---

## H. STORAGE REPORT

Local disk `/data/uploads` (10 GB) pins single instance. Upload = whole-file RAM; download = whole-file RAM + `Response(content=)`; S3 path identical (`Body.read()` whole) though correctly in `to_thread`. Signed URLs tutor-material only; submissions always proxy (auth-correct, RAM-costly). No orphan cleanup. S3 cutover blocked on bucket + flip + multi-instance audit. 20 MB × 20 concurrent ≈ 400 MB + b64 overhead — survives once, fails under burst.

---

## I. SCALE MODEL (assumptions: 1 tutor, 5 subjects, 2 assignments/wk/student, 1 past-paper/mo/student, ~5 topics/assignment, 3 dashboard visits/day/user, 60 s mean marking latency — sensitivity 30/180 s)

| Scale | Subs/wk | Marking jobs/wk | AI-h/wk @60 s | Serial drain | Evidence/wk | History/wk |
|---|---|---|---|---|---|---|
| 100 | 200 | ~225 | ~3.75 h | overnight OK, evening burst slow | ~1k | ~500 |
| 500 | 1000 | ~1125 | ~19 h | >2 days behind; 1000+ q analytics | ~5k | ~2.5k |
| 1000 | 2000 | ~2250 | ~37 h | never drains on bursts; 2005-q pages | ~10k | ~5k |
| 5000 | 10k | ~11k | ~187 h | needs 8–30 parallel workers | ~50k | ~25k |
| 10000 | 20k | ~22k | ~375 h | structural (pools, quotas, retention) | ~100k | ~50k |

Rows/year at 1000 students: evidence ~500k, history ~250k, snapshots ~250k, factor evals millions (T+6/run), usage/jobs ~120k each. No retention → operational pain in 12–18 months. Partitioning NOT justified yet.

---

## J. PRIORITIZED REMEDIATION ROADMAP

- **DO NOW:** AI timeouts + split session around AI calls; hung-job runbook (manual fail+requeue); 4 divergent + `past_paper_attempts` + `submission_files` indexes; paginate review-queue + submissions-by-assignment; bypass `analytics.py` via `groups.py`.
- **BEFORE 500:** marking vs fast-job lanes (2–4 workers); batch assessment/CRM/readiness queries; stream downloads; cap knowledge context; back off marking polls.
- **BEFORE 1000:** cursor pagination on all 28 lists; S3 cutover; PgBouncer/explicit pool + `pre_ping`; retention job; per-surface AI caps; shared HTTP/AI clients.
- **BEFORE 5000:** dashboard read replicas/CQRS; worker autoscale by queue depth; per-org AI quotas.
- **ONLY IF NEEDED:** dedicated executors; Redis cache for boundaries/subjects; Classroom cursors.
- **DO NOT DO:** microservices; sharding; Redis for app state; v1/v2 rewrite before queue+query fixes; bigger boxes to fix N+1.

---

## K. QUESTIONS FOR FOUNDER (mandatory — answers change the numbers)

1. Render instance RAM/CPU? Postgres `max_connections`, storage used GB?
2. Expected students/tutor (20/100/500?) and peak concurrent users?
3. Real submissions/student/week? Avg PDF pages + MB?
4. Measured AI latency p50/p95 per surface?
5. Provider rate limits + monthly AI budget? Is `AI_MODEL_PRICING` configured?
6. Are extra API replicas / separate worker planned, and when?
7. Must history/snapshots/usage be kept forever, or archivable after N months?
8. Acceptable marking SLA (minutes vs hours)? Dashboard p95 target?
9. Classroom: how many courses/tutors? Full or incremental sync?
10. Knowledge entries/tutor today and max KB text?

---

## L. CHALLENGE TO PRIOR AUDIT DOCS

| Prior claim | Verdict |
|---|---|
| N+1 fixed | PARTIALLY VERIFIED — fixed in `groups.py`/`today.py`, live in `analytics.py`, assessments, review-queue, CRM |
| FK indexes missing | VERIFIED (worse: +compound + PastPaperAttempt) |
| "29 lists, zero pagination" | PARTIALLY VERIFIED — true count **28 unbounded, 0 paginated** (3 on unmounted routers) |
| Serial worker | VERIFIED (exactly 1) |
| Single-instance constraint | VERIFIED (disk + in-process worker + no Redis) |
| Unbounded history | VERIFIED |
| Test/prod schema diff | VERIFIED (4 indexes) |
| AI spend risk | WORSE THAN DOCUMENTED (no timeout + txn-open + retry-duplicate + unbounded KB) |
| Blocking I/O | PARTIALLY VERIFIED (storage offloaded correctly; bcrypt + b64 on loop confirmed) |

---

## M. BOTTLENECK MAP + THE THREE QUESTIONS

```
USER BURST → API (OK) → POOL (OK@1) → QUERIES O(N) → QUEUE (FIFO) → WORKER=1 → AI (no timeout) → STORAGE (RAM)
               100: queries sting   500: queue collapses   1000+: structural   10k: volume
```

- **1,000 students tomorrow breaks first:** serial worker queue on any same-evening burst (hours of "being_marked"), analytics class pages second.
- **5,000 breaks first:** same queue (days behind) + unindexed evidence reads + 10 GB disk.
- **10,000 needs architecture:** workload-separated pools + pagination + S3 + pooler + retention + quotas. Bigger boxes alone cannot fix FIFO + O(N).

*End of report. Local-only artifact; nothing committed, pushed, or PR'd.*
