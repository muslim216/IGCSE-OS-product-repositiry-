# Avora v2 Audit — P1 Remediation Plan

> **What this is.** The execution plan closing the eleven P1 findings from
> `avora-production-readiness-audit-v2.md`. One PR per task, same rules as Phase 0: branch per
> task, never merge — the owner merges. Each PR is gated by the named ECC reviewer agents
> before it is opened; their findings are fixed or answered in the same PR.
>
> **Written:** 24 August 2026.

---

## Task 0 — Prerequisite (not a code change)

**Push and merge the five Phase-0a branches** (`fix/av-29-settled-statuses` first — 0.2 stacks
on it). Until 0.1 lands on default, readiness v2 scores from partial evidence. This is P1 #11
and it is pure merges, not code.

**Local hygiene:** delete the untracked Finder duplicates
(`backend/alembic/versions/0025_user_time_zone 2.py`, `backend/tests/test_ai_pricing 2.py`,
`docs/* 2.md`, `frontend/openapi 2.json`) — the test duplicate actively fails local pytest
with stale expectations.

## Quick fixes (one sitting each, S effort)

| ID | Branch | Fixes | Change | Verification | ECC gate |
|---|---|---|---|---|---|
| Q1 | `fix/job-reaper-startup-sweep` | P1-2 | In `main.py` lifespan: `UPDATE jobs SET status='pending' WHERE status='running'` before worker start (safe per BE-6); comment citing R5 | Test: seed `running` row → startup → row pending → `process_one_job` completes it | python-reviewer + silent-failure-hunter |
| Q2 | `fix/upload-size-before-read` | P1-10 | `storage.save_upload`: enforce 20 MB on source bytes via chunked read before decode/transcode (SEC-17 for the UploadFile path) | Oversized upload → 413 without full buffering; HEIC still transcodes | security-reviewer |
| Q3 | `fix/resubmission-audit-guard` | P1-5 | `submit_work`: if any `MarkOverrideAudit` exists for the submission's marks → 409 "tutor has reviewed this — ask them to reset it" (migration/cascade explicitly out of scope for this PR) | Test: audit row + resubmit → 409, submission intact | database-reviewer + pr-test-analyzer |
| Q4 | `fix/sdk-timeouts` | P1-6 | `get_client()`/Gemini client: explicit `timeout=` (chat ~60 s, bulk ~300 s) + `max_retries=1`; note at `JOB_STALL_SECONDS` | Unit: clients constructed with kwargs; manual: simulated hang no longer wedges queue | code-reviewer |
| Q5 | `fix/refetch-clobber-drafts` | P1-4 | QueryClient defaults (`staleTime: 30_000`, `refetchOnWindowFocus: false`) in `main.tsx`; dirty guards on SubmissionReviewPage/GradeBoundaries/TutorChat seeds; PreferencesPage gate render on load + mutation `onError`s | Component tests: refetch does not clobber dirty draft; save failure surfaces | react-reviewer + typescript-reviewer |
| Q6 | `fix/syllabus-metering` | P1-9 | Import + call `record_usage` post-parse with upload attribution (mirror `extraction.py:126-133`) | Negative test asserting an `ai_usage_events` row exists per extraction | code-reviewer |

## Larger fixes (need a decision or multi-site work)

| ID | Branch | Fixes | Change | Decision needed | ECC gate |
|---|---|---|---|---|---|
| W1 | `fix/admin-org-scoping` | P1-7 | Extract `today.py`'s three-clause check into one shared helper (`services/tenancy.py`); apply at all ~12 sites; extend `test_authorization.py` negatives | **Owner decides:** admin = org-scoped tutor (recommended, matches today.py/narrative.py) vs true superadmin | security-reviewer |
| W2 | `feat/ai-cost-throttles` | P1-8 | Per-student FixedWindowLimiter on `log_attempt`/`submit_work` AI triggers; block re-log while a mark job is pending/running; registration limiter on `/auth/register/*` | Cap numbers (suggest: 10 marking submissions/day/student) | security-reviewer |
| W3 | `ops/uploads-backup` | P1-1 | Render disk snapshot or scheduled S3 mirror + row↔file reconciliation script; runbook update; **rehearse R13 once** | Backup destination + schedule | — (infra, owner-executed steps documented in PR) |
| W4 | `ops/observability-floor` | P1-3 | `logging.basicConfig` JSON formatter + env level; request-id middleware; external uptime poll on `/health/ready`; optional Sentry DSN slot | Sentry yes/no; log drain destination | fastapi-reviewer |

**Suggested order:** Task 0 → Q1–Q6 (each independent; land as ready) → W1/W2 after the admin
semantics + cap decisions → W3/W4 alongside, since both have owner-side setup.

## P2 preview (next batch, not started)

QueryClient defaults beyond Q5's minimum · pricing/routing alignment when AV-124/task 3.2 runs
(paste dashboard pricing in that same PR) · metering conditional skips · DB-12 index
declarations ×4 models + `ai_usage_events` composite index · review-queue/group/analytics N+1
batching · `readiness.py:121` nullable score (+ FE-4 regen) · exactly-one-of CHECK constraints
· evidence `source_ref` unique index · Field component wiring `ApiError.fields` +
aria-invalid/onBlur · heading outline/h1 · blank-screen trio loading branches · JWT fail-fast ·
`.env.example` NARRATIVE_* family · CI coverage/pip-audit/npm audit/CodeQL · lockfile · HSTS.

## Rules carried forward

One PR per task · owner merges · constitution wins over ECC where they conflict · every fix
ships with its negative-case test (QA-12 spirit) · docs updated in the same PR where behaviour
affects them (GOV-1).
